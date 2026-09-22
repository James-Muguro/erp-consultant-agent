"""
Document Generator Tool - Creates formatted Word documents for ERP projects,
persisted durably in Postgres.

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

ACCENT_COLOR = RGBColor(0x1F, 0x5F, 0x4A)


# ----------------------------------------------------------------------
# Filename / path-component safety
# ----------------------------------------------------------------------

_UNSAFE_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
_PATH_SEPS_RE = re.compile(r'[\\/]+')
_WHITESPACE_RE = re.compile(r'\s+')

_WINDOWS_RESERVED_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)}
)


def _truncate_utf8(text: str, max_bytes: int) -> str:
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
    if value is None:
        return fallback
    text = str(value)
    text = _UNSAFE_CHARS_RE.sub('', text)
    text = _WHITESPACE_RE.sub('_', text.strip())
    text = _PATH_SEPS_RE.sub('-', text)
    text = text.strip('.-')
    if not text:
        return fallback
    stem = text.split('.', 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    encoded = text.encode('utf-8')
    if len(encoded) > max_bytes:
        digest = hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:8]
        suffix = f"_{digest}"
        budget = max_bytes - len(suffix.encode('ascii'))
        head = _truncate_utf8(text, max(0, budget))
        text = f"{head}{suffix}"
    return text


def _process_scoped_label(base: str, process_name: Any) -> str:
    safe = _sanitize_component(process_name, fallback="unnamed", max_bytes=48)
    digest = hashlib.sha256(str(process_name).encode('utf-8')).hexdigest()[:8]
    return f"{base}_{safe}_{digest}"


def _atomic_save_docx(doc: Document, final_path: Path) -> None:
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
        if subtitle_para.runs:
            subtitle_para.runs[0].italic = True
            subtitle_para.runs[0].font.size = Pt(11)
        doc.add_paragraph()
        return doc

    @staticmethod
    def _set_cell_text(cell, text: Any, bold: bool = False) -> None:
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
        if not isinstance(item, dict):
            return str(item)
        if 'condition' in item:
            condition = item.get('condition', '')
            outcomes = item.get('outcomes') or []
            if outcomes:
                branch = " / ".join(str(o) for o in outcomes)
                return f"{condition}  →  {branch}"
            return str(condition)
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
        if 'question' in item:
            topic = item.get('topic') or ''
            question = item.get('question') or ''
            owner = item.get('owner') or ''
            blocking = " [BLOCKING]" if item.get('blocking') else ""
            head = f"{topic}: {question}" if topic else question
            if owner:
                head = f"{head} (owner: {owner})"
            return f"{head}{blocking}"
        if 'description' in item:
            rid = item.get('id') or ''
            desc = item.get('description') or ''
            prio = item.get('priority') or ''
            bits = [f"[{rid}]" if rid else "", str(desc), f"({prio})" if prio else ""]
            return " ".join(b for b in bits if b)
        parts = [f"{k}={v}" for k, v in item.items() if v]
        return " | ".join(parts) if parts else str(item)

    def _add_bullet_list(self, doc: Document, items: List[Any]) -> None:
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
        if body and str(body).strip():
            doc.add_heading(heading, level=1)
            doc.add_paragraph(str(body))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _persist_to_db(self, session_id: str, phase: str, label: str, filepath: str) -> None:
        from sqlalchemy import update as sa_update

        from src.db.base import SessionLocal
        from src.db.models import GeneratedDocument

        with open(filepath, 'rb') as f:
            content = f.read()

        new_id = uuid.uuid4().hex

        db = SessionLocal()
        try:
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
            db.commit()
        except Exception:
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
        safe_prefix = _sanitize_component(prefix, fallback="document", max_bytes=48)
        safe_name = _sanitize_component(name, fallback="unnamed", max_bytes=64)
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
    # Requirements document
    # ------------------------------------------------------------------

    def generate_requirements_document(
        self,
        project_name: str,
        module: str,
        requirements: Dict[str, Any],
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document(
            "Business and Functional Requirements Specification",
            project_name,
        )
        reqs = requirements or {}
        meta = metadata or {}

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "Not provided") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _render_requirement_detail(req: dict) -> None:
            detail_rows = [
                ("Business Rationale", _or(req.get('rationale'))),
                ("Source", _or(req.get('source'))),
            ]
            source_excerpt = _clean(req.get('source_excerpt'))
            if source_excerpt:
                detail_rows.append(("Source Excerpt", source_excerpt))
            self._add_info_table(doc, detail_rows)

            ac_label_para = doc.add_paragraph()
            ac_label_run = ac_label_para.add_run("Acceptance Criteria")
            ac_label_run.bold = True
            ac = req.get('acceptance_criteria')
            if ac is None or (isinstance(ac, str) and not ac.strip()):
                doc.add_paragraph("To be confirmed.")
            elif isinstance(ac, (list, tuple)):
                if len(ac) == 0:
                    doc.add_paragraph("To be confirmed.")
                else:
                    for i, criterion in enumerate(ac, 1):
                        doc.add_paragraph(f"{i}. {criterion}")
            else:
                doc.add_paragraph(str(ac))

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        info_rows = [
            ("Project", project_name),
            ("Module", module),
        ]
        erp_system = _clean(meta.get('erp_system'))
        if erp_system:
            info_rows.append(("ERP System", erp_system))
        info_rows.extend([
            ("Document Type", "Business and Functional Requirements Specification"),
            ("Document Status", "Draft for Review"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])
        self._add_info_table(doc, info_rows)

        doc.add_heading(f"{section_num}. Executive Summary", level=1)
        section_num += 1
        doc.add_paragraph(_or(reqs.get('executive_summary'), "To be confirmed."))

        doc.add_heading(f"{section_num}. Business Context", level=1)
        section_num += 1
        doc.add_paragraph(_or(reqs.get('business_context')))

        doc.add_heading(f"{section_num}. Business Objectives", level=1)
        section_num += 1
        objectives = reqs.get('objectives') or []
        if objectives:
            self._add_bullet_list(doc, objectives)
        else:
            doc.add_paragraph("Not provided.")

        scope_text = _clean(reqs.get('scope'))
        scope_areas = reqs.get('scope_areas') or []
        scope_in = reqs.get('scope_in') or reqs.get('in_scope') or []
        scope_out = reqs.get('scope_out') or reqs.get('out_of_scope') or []
        if scope_text or scope_areas or scope_in or scope_out:
            doc.add_heading(f"{section_num}. Scope", level=1)
            section_num += 1
            if scope_text:
                doc.add_paragraph(scope_text)
            if scope_areas:
                doc.add_heading("Scope Areas", level=2)
                self._add_bullet_list(
                    doc,
                    scope_areas if isinstance(scope_areas, list) else [scope_areas],
                )
            if scope_in:
                doc.add_heading("In Scope", level=2)
                self._add_bullet_list(
                    doc,
                    scope_in if isinstance(scope_in, list) else [scope_in],
                )
            if scope_out:
                doc.add_heading("Out of Scope", level=2)
                self._add_bullet_list(
                    doc,
                    scope_out if isinstance(scope_out, list) else [scope_out],
                )

        functional_reqs = reqs.get('functional_requirements', {}) or {}
        nfr_raw = reqs.get('non_functional_requirements', []) or []
        tech_raw = reqs.get('technical_requirements', []) or []
        integ_raw = reqs.get('integration_requirements', []) or []
        report_raw = reqs.get('reporting_requirements', []) or []

        nfr_dicts = [r for r in nfr_raw if isinstance(r, dict)]
        nfr_strings = [r for r in nfr_raw if not isinstance(r, dict)]
        tech_dicts = [r for r in tech_raw if isinstance(r, dict)]
        tech_strings = [r for r in tech_raw if not isinstance(r, dict)]
        integ_dicts = [r for r in integ_raw if isinstance(r, dict)]
        integ_strings = [r for r in integ_raw if not isinstance(r, dict)]
        report_dicts = [r for r in report_raw if isinstance(r, dict)]
        report_strings = [r for r in report_raw if not isinstance(r, dict)]

        has_any_requirements = bool(
            any(functional_reqs.values())
            or nfr_raw or tech_raw or integ_raw or report_raw
        )

        if has_any_requirements:
            doc.add_heading(f"{section_num}. Requirements Overview", level=1)
            section_num += 1
            doc.add_paragraph(
                "This overview summarises every requirement captured in "
                "this document. Detailed content appears in the sections "
                "that follow."
            )
            overview_rows = []
            for category, cat_reqs in functional_reqs.items():
                for r in (cat_reqs or []):
                    if isinstance(r, dict):
                        overview_rows.append([
                            _or(r.get('id'), "—"),
                            str(category),
                            _or(r.get('priority'), "—"),
                            _or(r.get('req_type') or r.get('type'), "Functional"),
                            _or(r.get('status'), "—"),
                        ])
                    else:
                        overview_rows.append(["—", str(category), "—", "Functional", "—"])
            for r in nfr_dicts:
                overview_rows.append([
                    _or(r.get('id'), "—"),
                    _or(r.get('category'), "Non-Functional"),
                    _or(r.get('priority'), "—"),
                    _or(r.get('req_type') or r.get('type'), "Non-Functional"),
                    _or(r.get('status'), "—"),
                ])
            for r in tech_dicts:
                overview_rows.append([
                    _or(r.get('id'), "—"),
                    _or(r.get('category'), "Technical"),
                    _or(r.get('priority'), "—"),
                    _or(r.get('req_type') or r.get('type'), "Technical"),
                    _or(r.get('status'), "—"),
                ])
            for r in integ_dicts:
                overview_rows.append([
                    _or(r.get('id'), "—"),
                    _or(r.get('category'), "Integration"),
                    _or(r.get('priority'), "—"),
                    _or(r.get('req_type') or r.get('type'), "Integration"),
                    _or(r.get('status'), "—"),
                ])
            for r in report_dicts:
                overview_rows.append([
                    _or(r.get('id'), "—"),
                    _or(r.get('category'), "Reporting"),
                    _or(r.get('priority'), "—"),
                    _or(r.get('req_type') or r.get('type'), "Reporting"),
                    _or(r.get('status'), "—"),
                ])
            if overview_rows:
                self._add_data_table(
                    doc,
                    ["Requirement ID", "Category", "Priority", "Type", "Status"],
                    overview_rows,
                )
            else:
                doc.add_paragraph("No structured requirement identifiers available.")

        if functional_reqs:
            doc.add_heading(f"{section_num}. Functional Requirements", level=1)
            section_num += 1
            any_rendered = False
            for category, cat_reqs in functional_reqs.items():
                cat_list = list(cat_reqs or [])
                if not cat_list:
                    continue
                any_rendered = True
                doc.add_heading(str(category), level=2)
                norm = []
                for r in cat_list:
                    if isinstance(r, dict):
                        norm.append(r)
                    else:
                        norm.append({'description': str(r)})
                summary_rows = []
                for r in norm:
                    summary_rows.append([
                        _or(r.get('id'), "—"),
                        _or(r.get('description'), "—"),
                        _or(r.get('priority'), "—"),
                        _or(r.get('req_type') or r.get('type'), "Functional"),
                        _or(r.get('status'), "—"),
                    ])
                self._add_data_table(
                    doc,
                    ["Requirement ID", "Description", "Priority", "Type", "Status"],
                    summary_rows,
                )
                for r in norm:
                    has_detail = any([
                        _clean(r.get('rationale')),
                        _clean(r.get('source')),
                        _clean(r.get('source_excerpt')),
                        r.get('acceptance_criteria'),
                    ])
                    if not has_detail:
                        continue
                    rid = _or(r.get('id'), "Requirement")
                    doc.add_heading(str(rid), level=3)
                    _render_requirement_detail(r)
            if not any_rendered:
                doc.add_paragraph("No functional requirements were specified in the source data.")

        if nfr_raw:
            doc.add_heading(f"{section_num}. Non-Functional Requirements", level=1)
            section_num += 1
            if nfr_dicts:
                structured = any(
                    any(r.get(k) for k in (
                        'id', 'priority', 'status', 'req_type', 'type',
                        'acceptance_criteria', 'rationale', 'source',
                        'source_excerpt',
                    ))
                    for r in nfr_dicts
                )
                if structured:
                    summary_rows = []
                    for r in nfr_dicts:
                        summary_rows.append([
                            _or(r.get('id'), "—"),
                            _or(r.get('description'), "—"),
                            _or(r.get('priority'), "—"),
                            _or(r.get('req_type') or r.get('type'), "Non-Functional"),
                            _or(r.get('status'), "—"),
                        ])
                    self._add_data_table(
                        doc,
                        ["Requirement ID", "Description", "Priority", "Type", "Status"],
                        summary_rows,
                    )
                    for r in nfr_dicts:
                        has_detail = any([
                            _clean(r.get('rationale')),
                            _clean(r.get('source')),
                            _clean(r.get('source_excerpt')),
                            r.get('acceptance_criteria'),
                        ])
                        if not has_detail:
                            continue
                        rid = _or(r.get('id'), "Requirement")
                        doc.add_heading(str(rid), level=2)
                        _render_requirement_detail(r)
                else:
                    self._add_bullet_list(
                        doc,
                        [r.get('description', '') for r in nfr_dicts],
                    )
            if nfr_strings:
                self._add_bullet_list(doc, nfr_strings)

        for label, dicts, strings in (
            ("Technical Requirements", tech_dicts, tech_strings),
            ("Integration Requirements", integ_dicts, integ_strings),
            ("Reporting Requirements", report_dicts, report_strings),
        ):
            if not dicts and not strings:
                continue
            doc.add_heading(f"{section_num}. {label}", level=1)
            section_num += 1
            structured = any(
                any(r.get(k) for k in (
                    'id', 'priority', 'status', 'req_type', 'type',
                    'acceptance_criteria', 'rationale', 'source',
                    'source_excerpt',
                ))
                for r in dicts
            )
            if structured:
                summary_rows = []
                for r in dicts:
                    summary_rows.append([
                        _or(r.get('id'), "—"),
                        _or(r.get('description'), "—"),
                        _or(r.get('priority'), "—"),
                        _or(r.get('req_type') or r.get('type'), label.split()[0]),
                        _or(r.get('status'), "—"),
                    ])
                self._add_data_table(
                    doc,
                    ["Requirement ID", "Description", "Priority", "Type", "Status"],
                    summary_rows,
                )
                for r in dicts:
                    has_detail = any([
                        _clean(r.get('rationale')),
                        _clean(r.get('source')),
                        _clean(r.get('source_excerpt')),
                        r.get('acceptance_criteria'),
                    ])
                    if not has_detail:
                        continue
                    rid = _or(r.get('id'), "Requirement")
                    doc.add_heading(str(rid), level=2)
                    _render_requirement_detail(r)
                if strings:
                    doc.add_heading("Additional Requirements", level=2)
                    self._add_bullet_list(doc, strings)
            else:
                items = [r.get('description', '') for r in dicts]
                items.extend(strings)
                self._add_bullet_list(doc, items)

        dependencies = reqs.get('dependencies') or []
        constraints = reqs.get('constraints') or []
        if dependencies or constraints:
            doc.add_heading(f"{section_num}. Dependencies and Constraints", level=1)
            section_num += 1
            if dependencies:
                doc.add_heading("Dependencies", level=2)
                self._add_bullet_list(doc, dependencies)
            if constraints:
                doc.add_heading("Constraints", level=2)
                self._add_bullet_list(doc, constraints)

        assumptions = reqs.get('assumptions') or []
        if assumptions:
            doc.add_heading(f"{section_num}. Assumptions", level=1)
            section_num += 1
            self._add_bullet_list(doc, assumptions)

        open_qs = reqs.get('open_questions') or []
        if open_qs:
            doc.add_heading(f"{section_num}. Open Questions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Open questions remain unresolved. Blocking items must be "
                "resolved before the affected requirements can be confirmed."
            )
            rows = []
            for q in open_qs:
                if isinstance(q, dict):
                    rows.append([
                        _or(q.get('question'), "—"),
                        _or(q.get('context') or q.get('topic'), ""),
                        _or(q.get('source'), ""),
                        _or(q.get('owner'), ""),
                        "Yes" if q.get('blocking') else "No",
                    ])
                else:
                    rows.append([str(q), "", "", "", "No"])
            self._add_data_table(
                doc,
                ["Question", "Context", "Source", "Owner", "Blocking"],
                rows,
            )

        trace_rows = []
        for category, cat_reqs in functional_reqs.items():
            for r in (cat_reqs or []):
                if isinstance(r, dict):
                    trace_rows.append([
                        _or(r.get('id'), "—"),
                        str(category),
                        _or(r.get('description'), "—"),
                        _or(r.get('priority'), "—"),
                        _or(r.get('status'), "—"),
                    ])
        for r in nfr_dicts:
            trace_rows.append([
                _or(r.get('id'), "—"),
                _or(r.get('category'), "Non-Functional"),
                _or(r.get('description'), "—"),
                _or(r.get('priority'), "—"),
                _or(r.get('status'), "—"),
            ])
        for r in tech_dicts:
            trace_rows.append([
                _or(r.get('id'), "—"),
                _or(r.get('category'), "Technical"),
                _or(r.get('description'), "—"),
                _or(r.get('priority'), "—"),
                _or(r.get('status'), "—"),
            ])
        for r in integ_dicts:
            trace_rows.append([
                _or(r.get('id'), "—"),
                _or(r.get('category'), "Integration"),
                _or(r.get('description'), "—"),
                _or(r.get('priority'), "—"),
                _or(r.get('status'), "—"),
            ])
        for r in report_dicts:
            trace_rows.append([
                _or(r.get('id'), "—"),
                _or(r.get('category'), "Reporting"),
                _or(r.get('description'), "—"),
                _or(r.get('priority'), "—"),
                _or(r.get('status'), "—"),
            ])
        if trace_rows:
            doc.add_heading(f"{section_num}. Requirements Traceability", level=1)
            section_num += 1
            doc.add_paragraph(
                "This table establishes the canonical requirement "
                "identifiers used by downstream phases (process mapping, "
                "solution design, QA, UAT, and training). Downstream links "
                "are recorded in their own artefacts, not here."
            )
            self._add_data_table(
                doc,
                ["Requirement ID", "Category", "Description", "Priority", "Status"],
                trace_rows,
            )

        doc.add_heading(f"{section_num}. Review and Approval", level=1)
        section_num += 1
        doc.add_paragraph(
            "This document is a draft for review. Fields marked "
            "'To be completed' remain outstanding."
        )
        self._add_data_table(
            doc,
            ["Review Role", "Name", "Review Status", "Review Date", "Comments"],
            [
                ["Business Owner", "", "To be completed", "", ""],
                ["Project Manager", "", "To be completed", "", ""],
                ["Technical Lead", "", "To be completed", "", ""],
                ["Functional Consultant", "", "To be completed", "", ""],
            ],
        )

        sid = session_id or meta.get('session_id')
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
    # Requirements questionnaire
    # ------------------------------------------------------------------

    def generate_requirements_template(
        self,
        project_name: str,
        module: str,
        erp_system: str,
        context: Dict[str, str],
        session_id: Optional[str] = None,
    ) -> str:
        doc = self._new_document("ERP Requirements Discovery Workbook", project_name)
        ctx = context or {}

        def _or(value: Any, placeholder: str = "To be confirmed") -> str:
            s = str(value).strip() if value is not None else ""
            return s if s else placeholder

        def _blank(n: int, cols: int) -> List[List[str]]:
            return [["" for _ in range(cols)] for _ in range(n)]

        doc.add_heading("1. Document Information", level=1)
        self._add_info_table(doc, [
            ("Project", project_name),
            ("Module / Functional Area", module),
            ("ERP System", _or(erp_system)),
            ("Document Type", "ERP Requirements Discovery Workbook"),
            ("Document Status", "Draft for Completion"),
            ("Version", "1.0"),
            ("Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading("2. Session Instructions", level=1)
        doc.add_heading("Purpose of this Workbook", level=2)
        doc.add_paragraph(
            "This workbook captures the business context, objectives, "
            "scope, current-state process, business needs, and requirements "
            "for the scope identified in Section 1. It is used during "
            "requirements discovery and its output feeds directly into the "
            "Business and Functional Requirements Specification."
        )
        doc.add_heading("Who Should Complete It", level=2)
        doc.add_paragraph(
            "Business stakeholders, process owners, and subject matter "
            "experts complete the workbook together with the functional "
            "consultant. The consultant consolidates responses and resolves "
            "open questions before the Requirements Specification is "
            "produced."
        )
        doc.add_heading("How It Will Be Used", level=2)
        doc.add_paragraph(
            "Completed responses become the evidence base for the "
            "Requirements Specification, Process Map, Solution Design, QA, "
            "UAT, and Training artefacts. Unresolved items are recorded as "
            "open questions rather than assumed or guessed."
        )
        doc.add_heading("How to Use This Workbook", level=2)
        instructions = [
            "Answer from the business perspective. Describe what the business needs, not how the ERP should be configured.",
            "Record facts, decisions, and assumptions separately. Do not present an assumption as a confirmed fact.",
            "Do not guess missing information. Where an answer is not yet known, record it as an open question in Section 16.",
            "Prioritise required business outcomes over solution preferences.",
            "Use one row per requirement, pain point, or question. Do not combine multiple items into a single row.",
            "Return the completed workbook to the functional consultant for consolidation.",
        ]
        for item in instructions:
            doc.add_paragraph(item, style='List Bullet')

        doc.add_heading("3. Business Context", level=1)
        doc.add_paragraph(
            "This section records the organisational context for the scope. "
            "Values supplied at intake are shown; complete any fields that "
            "remain \"To be confirmed\"."
        )
        doc.add_heading("Provided Intake Information", level=2)
        self._add_data_table(doc, ["Field", "Value"], [
            ["Industry", _or(ctx.get('industry'))],
            ["Organisation Size", _or(ctx.get('company_size'))],
            ["Primary Business Goal (from intake)", _or(ctx.get('primary_goal'))],
            ["Scope Areas (from intake)", _or(ctx.get('scope_areas'))],
        ])
        doc.add_heading("Additional Context", level=2)
        doc.add_paragraph(
            "Describe the organisational context that affects this scope: "
            "affected business units, operating environment, key drivers, "
            "and any external factors."
        )
        self._add_data_table(doc, ["Prompt", "Response"], [
            ["Affected business units / teams", ""],
            ["Operating environment or site considerations", ""],
            ["Key internal or external business drivers", ""],
            ["Anything else that shapes this scope", ""],
        ])

        doc.add_heading("4. Business Objectives and Success Measures", level=1)
        doc.add_paragraph(
            "List the business objectives this scope must support. State the "
            "reason the objective matters, the expected business outcome, "
            "and — where it can be defined — the measure that will indicate "
            "success. Objectives are not requirements."
        )
        self._add_data_table(
            doc,
            ["#", "Objective", "Reason",
             "Expected Business Outcome", "Success Measure", "Owner"],
            [[str(i + 1), "", "", "", "", ""] for i in range(5)],
        )

        doc.add_heading("5. Scope and Boundaries", level=1)
        doc.add_paragraph(
            "Define what this scope covers and what it explicitly does not "
            "cover. Scope boundaries are decisions, not assumptions. Where a "
            "boundary is not yet decided, record it as an open question in "
            "Section 16."
        )
        doc.add_heading("In Scope", level=2)
        self._add_data_table(
            doc,
            ["Area / Process", "Explanation", "Owner / Decision Maker"],
            _blank(5, 3),
        )
        doc.add_heading("Out of Scope", level=2)
        self._add_data_table(
            doc,
            ["Area / Process", "Reason for Exclusion", "Owner / Decision Maker"],
            _blank(5, 3),
        )

        doc.add_heading("6. Stakeholders and Roles", level=1)
        doc.add_paragraph(
            "Identify the people involved in this scope. In the Role Type "
            "column, use one of: Process Owner, Subject Matter Expert, "
            "Approver, End User."
        )
        self._add_data_table(
            doc,
            ["Name", "Role / Title", "Business Area",
             "Responsibility", "Decision Authority", "Role Type"],
            _blank(6, 6),
        )

        doc.add_heading("7. Current-State Process", level=1)
        doc.add_paragraph(
            "Describe how the process operates today, before any ERP "
            "change. This becomes the evidence base for the Process Map."
        )
        doc.add_heading("Process Overview", level=2)
        self._add_data_table(doc, ["Prompt", "Response"], [
            ["Process name", ""],
            ["Process purpose", ""],
            ["Process trigger", ""],
            ["Process end / completion condition", ""],
            ["Frequency / volume", ""],
        ])
        doc.add_heading("Process Steps", level=2)
        doc.add_paragraph(
            "List the steps in sequence. Include the actor who performs "
            "each step, the system used, and any control applied."
        )
        self._add_data_table(
            doc,
            ["#", "Step", "Actor / Role", "System Used",
             "Input", "Output", "Control / Check"],
            [[str(i + 1), "", "", "", "", "", ""] for i in range(8)],
        )
        doc.add_heading("Manual Work, Exceptions, and Issues", level=2)
        self._add_data_table(doc, ["Prompt", "Response"], [
            ["Manual workarounds currently used", ""],
            ["Common exceptions and how they are handled", ""],
            ["Where the process most often fails or slows down", ""],
        ])

        doc.add_heading("8. Pain Points and Business Needs", level=1)
        doc.add_paragraph(
            "List the problems the business experiences today. For each "
            "entry record the impact and the outcome the business wants. "
            "Describe the need, not the solution."
        )
        self._add_data_table(
            doc,
            ["#", "Current Problem", "Business Impact",
             "Affected Users / Process", "Frequency / Significance",
             "Desired Outcome"],
            [[str(i + 1), "", "", "", "", ""] for i in range(6)],
        )

        doc.add_heading("9. Functional Requirements", level=1)
        doc.add_paragraph(
            "Capture each business requirement as a capability or outcome "
            "the business needs. A useful requirement states what is "
            "needed, who needs it, the expected outcome, and the condition "
            "that must be satisfied. Avoid wording that assumes a specific "
            "technical solution unless the technical constraint itself is "
            "the requirement."
        )
        doc.add_paragraph(
            "Requirement IDs are assigned by the platform when the "
            "Requirements Specification is produced. Leave the ID column "
            "as \"To be assigned\"; the canonical identifiers will be "
            "reconciled from the structured requirement data, not from "
            "this workbook."
        )
        doc.add_heading("Requirement Register", level=2)
        self._add_data_table(
            doc,
            ["ID", "Business Requirement", "Description",
             "Priority", "Requirement Type"],
            [["To be assigned", "", "", "", ""] for _ in range(8)],
        )
        doc.add_heading("Rationale, Source, and Acceptance Criteria", level=2)
        doc.add_paragraph(
            "For each requirement recorded above, record why it exists, "
            "where it comes from, and how it will be accepted. Use the "
            "requirement reference from the register."
        )
        self._add_data_table(
            doc,
            ["Requirement Reference", "Rationale", "Source",
             "Source Excerpt / Supporting Statement",
             "Acceptance Criteria", "Dependencies", "Assumptions"],
            [["", "", "", "", "", "", ""] for _ in range(8)],
        )

        doc.add_heading("10. Non-Functional Requirements", level=1)
        doc.add_paragraph(
            "Capture quality attributes and constraints the solution must "
            "satisfy. Consider performance, availability, security, "
            "usability, auditability, scalability, and data retention. "
            "State measurable targets only where the business has agreed "
            "them."
        )
        self._add_data_table(
            doc,
            ["#", "Quality / Constraint", "Requirement",
             "Reason", "Priority", "Acceptance Criteria"],
            [[str(i + 1), "", "", "", "", ""] for i in range(6)],
        )

        doc.add_heading("11. Data and Reporting Requirements", level=1)
        doc.add_paragraph(
            "Capture business needs for data and reporting. Describe what "
            "is required and why; do not specify technical data models or "
            "report layouts here."
        )
        doc.add_heading("Data", level=2)
        self._add_data_table(
            doc,
            ["Data Type", "Master / Transactional", "Owner",
             "Known Quality Issues", "Migration Considerations"],
            _blank(5, 5),
        )
        doc.add_heading("Reporting and Analytics", level=2)
        self._add_data_table(
            doc,
            ["Report / Insight", "Audience", "Purpose",
             "Frequency", "Key Information Required"],
            _blank(5, 5),
        )

        doc.add_heading("12. Integration Requirements", level=1)
        doc.add_paragraph(
            "Identify external systems the business relies on and the "
            "information that must flow between them. Describe the "
            "business purpose and timing. Do not specify APIs or "
            "integration architecture."
        )
        self._add_data_table(
            doc,
            ["System", "Business Purpose", "Information Exchanged",
             "Frequency / Timing", "Business Owner", "Known Constraints"],
            _blank(6, 6),
        )

        doc.add_heading("13. Controls, Compliance, and Audit Requirements", level=1)
        doc.add_paragraph(
            "Identify approvals, segregation-of-duties controls, audit "
            "requirements, regulatory obligations, and mandatory evidence "
            "that apply to this scope. Record the source of each "
            "requirement (internal policy, regulation, contractual). Do "
            "not assume a regulation applies; ask the stakeholder to "
            "identify it."
        )
        self._add_data_table(
            doc,
            ["Area / Process", "Control or Obligation", "Source",
             "Evidence Required", "Owner"],
            _blank(6, 5),
        )

        doc.add_heading("14. Dependencies and Constraints", level=1)
        doc.add_paragraph(
            "Record dependencies the scope relies on and constraints the "
            "solution must operate within. A constraint is not a "
            "requirement unless the business has expressed it as a need."
        )
        doc.add_heading("Dependencies", level=2)
        self._add_data_table(
            doc,
            ["#", "Dependency", "Impact", "Owner"],
            [[str(i + 1), "", "", ""] for i in range(5)],
        )
        doc.add_heading("Constraints", level=2)
        self._add_data_table(
            doc,
            ["#", "Constraint", "Impact", "Owner"],
            [[str(i + 1), "", "", ""] for i in range(5)],
        )

        doc.add_heading("15. Assumptions", level=1)
        doc.add_paragraph(
            "Record the assumptions this scope is operating under. State "
            "the basis for each assumption and the validation it requires. "
            "Do not present an assumption as a confirmed fact."
        )
        self._add_data_table(
            doc,
            ["#", "Assumption", "Basis / Source", "Validation Needed"],
            [[str(i + 1), "", "", ""] for i in range(6)],
        )

        doc.add_heading("16. Open Questions", level=1)
        doc.add_paragraph(
            "Record every question that must be resolved before the "
            "Requirements Specification can be finalised. Mark as Blocking "
            "any question whose unresolved state prevents requirements "
            "from being confirmed."
        )
        self._add_data_table(
            doc,
            ["#", "Question", "Context", "Owner",
             "Blocking?", "Target Decision Date"],
            [[str(i + 1), "", "", "", "", ""] for i in range(6)],
        )

        doc.add_heading("17. Priority and Business Value", level=1)
        doc.add_paragraph(
            "For the highest-priority requirements captured in Section 9, "
            "explain the business value delivered and the impact if the "
            "requirement is not met. Use the priority terminology already "
            "agreed by the project; do not introduce a new priority scale."
        )
        self._add_data_table(
            doc,
            ["Requirement Reference", "Priority", "Business Value",
             "Impact if Unmet"],
            _blank(6, 4),
        )

        doc.add_heading("18. Requirement Validation", level=1)
        doc.add_paragraph(
            "This section supports review of the completed workbook before "
            "it is consolidated into the Requirements Specification. "
            "Confirmation here is a review, not an approval of the final "
            "Requirements Specification."
        )
        doc.add_heading("Validation Checklist", level=2)
        self._add_data_table(
            doc,
            ["Item", "Confirmed? (Yes / No)", "Comments"],
            [
                ["Scope boundaries are understood and agreed.", "", ""],
                ["Business objectives and success measures are captured.", "", ""],
                ["Functional requirements are clear and complete.", "", ""],
                ["Non-functional requirements are captured where applicable.", "", ""],
                ["Priorities are agreed with the business.", "", ""],
                ["Acceptance criteria are testable where possible.", "", ""],
                ["Assumptions are recorded with their basis.", "", ""],
                ["Open questions are visible with owners and target dates.", "", ""],
                ["Unresolved items are acknowledged and assigned.", "", ""],
            ],
        )
        doc.add_heading("Review Record", level=2)
        doc.add_paragraph(
            "Complete the review record with the names and dates of the "
            "reviewers. Names and dates are not generated by the platform."
        )
        self._add_data_table(
            doc,
            ["Reviewer", "Role", "Review Date", "Review Status", "Comments"],
            _blank(5, 5),
        )

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
        pm = process_map or {}

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "Not provided") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _as_bullets(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [str(v) for v in value if v is not None and str(v).strip()]
            s = str(value).strip()
            return [s] if s else []

        def _step_id(step: Any, idx: int) -> str:
            if isinstance(step, dict):
                sid = _clean(step.get('id'))
                if sid:
                    return sid
                num = step.get('number')
                if num not in (None, ""):
                    return str(num)
            return str(idx + 1)

        def _step_number(step: Any, idx: int) -> str:
            if isinstance(step, dict):
                num = step.get('number')
                if num not in (None, ""):
                    return str(num)
            return str(idx + 1)

        def _step_name(step: Any) -> str:
            if isinstance(step, dict):
                return _clean(step.get('name')) or _clean(step.get('title')) or "Process Step"
            return _clean(step) or "Process Step"

        def _step_requirement_ids(step: Any) -> List[str]:
            if not isinstance(step, dict):
                return []
            ids: List[str] = []
            for key in ('requirement_id', 'related_requirement_ids', 'requirement_ids'):
                v = step.get(key)
                if v in (None, "", []):
                    continue
                if isinstance(v, (list, tuple)):
                    ids.extend(str(x) for x in v if x not in (None, ""))
                else:
                    ids.append(str(v))
            seen = set()
            out = []
            for x in ids:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        def _dict_or_str_list(value: Any) -> List[Any]:
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [v for v in value if v is not None and (not isinstance(v, str) or v.strip())]
            return [value]

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        self._add_info_table(doc, [
            ("Project", project_name),
            ("Module", module),
            ("Process", process_name),
            ("Document Type", "Process Map"),
            ("Document Status", "Draft for Review"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        overview = _clean(pm.get('overview'))
        business_outcome = _clean(pm.get('business_outcome')) or _clean(pm.get('purpose'))
        primary_participants_raw = pm.get('primary_participants')
        primary_participants_list = _as_bullets(primary_participants_raw)
        state_text = _clean(pm.get('as_is_or_to_be'))
        if state_text.lower() in ('unspecified', 'not specified'):
            state_text = ""

        if overview or business_outcome or primary_participants_list or state_text:
            doc.add_heading(f"{section_num}. Process Summary", level=1)
            section_num += 1
            if overview:
                doc.add_heading("Process Purpose", level=2)
                doc.add_paragraph(overview)
            if business_outcome:
                doc.add_heading("Business Outcome", level=2)
                doc.add_paragraph(business_outcome)
            if state_text:
                doc.add_heading("Process State", level=2)
                doc.add_paragraph(state_text)
            if primary_participants_list:
                doc.add_heading("Primary Participants", level=2)
                self._add_bullet_list(doc, primary_participants_list)

        scope_text = _clean(pm.get('scope'))
        scope_in = pm.get('scope_in') or pm.get('in_scope') or []
        scope_out = pm.get('scope_out') or pm.get('out_of_scope') or []
        if scope_text or scope_in or scope_out:
            doc.add_heading(f"{section_num}. Scope", level=1)
            section_num += 1
            if scope_text:
                doc.add_paragraph(scope_text)
            if scope_in:
                doc.add_heading("In Scope", level=2)
                self._add_bullet_list(
                    doc, scope_in if isinstance(scope_in, list) else [scope_in],
                )
            if scope_out:
                doc.add_heading("Out of Scope", level=2)
                self._add_bullet_list(
                    doc, scope_out if isinstance(scope_out, list) else [scope_out],
                )

        roles_raw = pm.get('roles') or []
        roles_list = _dict_or_str_list(roles_raw)
        if roles_list:
            doc.add_heading(f"{section_num}. Roles and Responsibilities", level=1)
            section_num += 1
            has_structured = any(isinstance(r, dict) for r in roles_list)
            if has_structured:
                rows = []
                for r in roles_list:
                    if isinstance(r, dict):
                        role_name = _or(r.get('role') or r.get('name'), "—")
                        responsibility = _or(r.get('responsibility'), "Not provided")
                        participation = _or(
                            r.get('process_participation') or r.get('participation'),
                            "Not provided",
                        )
                        rows.append([role_name, responsibility, participation])
                    else:
                        rows.append([str(r), "Not provided", "Not provided"])
                self._add_data_table(
                    doc,
                    ["Role", "Responsibility", "Process Participation"],
                    rows,
                )
            else:
                self._add_bullet_list(doc, [str(r) for r in roles_list])

        steps_raw = pm.get('steps') or []
        steps = list(steps_raw) if isinstance(steps_raw, (list, tuple)) else []

        if steps:
            doc.add_heading(f"{section_num}. Process Steps", level=1)
            section_num += 1
            doc.add_paragraph(
                "Steps are listed in process sequence. Step identifiers "
                "are preserved from the source process data and are "
                "referenced by downstream artefacts (solution design, QA, "
                "UAT, training)."
            )
            summary_rows = []
            for i, s in enumerate(steps):
                sid = _step_id(s, i)
                snum = _step_number(s, i)
                sname = _step_name(s)
                if isinstance(s, dict):
                    role = _or(s.get('responsible_role'), "—")
                    transaction = _or(s.get('transaction'), "—")
                    description = _or(s.get('description'), "—")
                else:
                    role = "—"
                    transaction = "—"
                    description = "—"
                req_ids = _step_requirement_ids(s)
                req_ref = ", ".join(req_ids) if req_ids else "—"
                summary_rows.append([
                    sid, snum, sname, role, transaction, description, req_ref,
                ])
            self._add_data_table(
                doc,
                [
                    "Step ID", "Step Number", "Process Step",
                    "Responsible Role", "Transaction / Activity",
                    "Description", "Requirement Reference",
                ],
                summary_rows,
            )

        if steps:
            detail_blocks: List[tuple] = []
            for i, s in enumerate(steps):
                if not isinstance(s, dict):
                    continue
                trigger = _clean(s.get('trigger'))
                transaction = _clean(s.get('transaction'))
                description = _clean(s.get('description'))
                inputs = _as_bullets(s.get('inputs'))
                outputs = _as_bullets(s.get('outputs'))
                exceptions = _as_bullets(s.get('exception_paths') or s.get('exceptions'))
                controls = _as_bullets(s.get('controls'))
                notes = _clean(s.get('notes'))
                req_ids = _step_requirement_ids(s)
                has_detail = any([
                    trigger, transaction, description,
                    inputs, outputs, exceptions, controls, notes, req_ids,
                ])
                if has_detail:
                    detail_blocks.append((i, s, {
                        'trigger': trigger,
                        'transaction': transaction,
                        'description': description,
                        'inputs': inputs,
                        'outputs': outputs,
                        'exceptions': exceptions,
                        'controls': controls,
                        'notes': notes,
                        'requirement_ids': req_ids,
                    }))
            if detail_blocks:
                doc.add_heading(f"{section_num}. Step Details", level=1)
                section_num += 1
                doc.add_paragraph(
                    "Each block below records the step-level detail supplied "
                    "in the source process data. Fields with no source "
                    "value are omitted."
                )
                for (i, s, det) in detail_blocks:
                    sid = _step_id(s, i)
                    sname = _step_name(s)
                    role = _clean(s.get('responsible_role'))
                    doc.add_heading(f"{sid} — {sname}", level=2)
                    info_rows = []
                    if role:
                        info_rows.append(("Responsible Role", role))
                    if det['trigger']:
                        info_rows.append(("Trigger", det['trigger']))
                    if det['transaction']:
                        info_rows.append(("Transaction / Activity", det['transaction']))
                    if det['description']:
                        info_rows.append(("Description", det['description']))
                    if det['requirement_ids']:
                        info_rows.append((
                            "Requirement References",
                            ", ".join(det['requirement_ids']),
                        ))
                    if info_rows:
                        self._add_info_table(doc, info_rows)
                    if det['inputs']:
                        doc.add_heading("Inputs", level=3)
                        self._add_bullet_list(doc, det['inputs'])
                    if det['outputs']:
                        doc.add_heading("Outputs", level=3)
                        self._add_bullet_list(doc, det['outputs'])
                    if det['exceptions']:
                        doc.add_heading("Exceptions", level=3)
                        self._add_bullet_list(doc, det['exceptions'])
                    if det['controls']:
                        doc.add_heading("Controls", level=3)
                        self._add_bullet_list(doc, det['controls'])
                    if det['notes']:
                        doc.add_heading("Notes", level=3)
                        doc.add_paragraph(det['notes'])

        step_to_reqs: List[List[str]] = []
        req_to_steps: Dict[str, List[str]] = {}
        for i, s in enumerate(steps):
            req_ids = _step_requirement_ids(s)
            if not req_ids:
                continue
            sid = _step_id(s, i)
            sname = _step_name(s)
            for rid in req_ids:
                step_to_reqs.append([rid, sid, sname])
                req_to_steps.setdefault(rid, []).append(sid)
        if step_to_reqs:
            doc.add_heading(f"{section_num}. Requirement Traceability", level=1)
            section_num += 1
            doc.add_paragraph(
                "The relationships below are sourced from the structured "
                "process data. They are not inferred. Where a step has no "
                "requirement link in the source, no link is shown."
            )
            doc.add_heading("Step to Requirement", level=2)
            self._add_data_table(
                doc,
                ["Requirement ID", "Step ID", "Step Name"],
                step_to_reqs,
            )
            doc.add_heading("Requirement to Step", level=2)
            req_summary_rows = []
            for rid, sids in req_to_steps.items():
                req_summary_rows.append([rid, ", ".join(sids)])
            self._add_data_table(
                doc,
                ["Requirement ID", "Related Step IDs"],
                req_summary_rows,
            )
        elif steps:
            doc.add_heading(f"{section_num}. Requirement Traceability", level=1)
            section_num += 1
            doc.add_paragraph(
                "No requirement linkage provided in the source process "
                "data. Requirement relationships will be captured when the "
                "linkage is available."
            )

        decision_points = pm.get('decision_points') or []
        if decision_points:
            doc.add_heading(f"{section_num}. Decision Points", level=1)
            section_num += 1
            has_structured_dp = any(isinstance(d, dict) for d in decision_points)
            if has_structured_dp:
                rows = []
                for d in decision_points:
                    if isinstance(d, dict):
                        rows.append([
                            _or(d.get('decision') or d.get('condition'), "—"),
                            _or(d.get('condition'), "—"),
                            _or(
                                d.get('outcome')
                                or d.get('path')
                                or " / ".join(_as_bullets(d.get('outcomes'))),
                                "—",
                            ),
                        ])
                    else:
                        rows.append([str(d), "—", "—"])
                self._add_data_table(
                    doc,
                    ["Decision", "Condition", "Outcome / Path"],
                    rows,
                )
            else:
                self._add_bullet_list(doc, decision_points)

        integration_points = pm.get('integration_points') or []
        if integration_points:
            doc.add_heading(f"{section_num}. Integration Points", level=1)
            section_num += 1
            has_structured_ip = any(isinstance(p, dict) for p in integration_points)
            if has_structured_ip:
                rows = []
                for p in integration_points:
                    if isinstance(p, dict):
                        rows.append([
                            _or(p.get('name') or p.get('integration'), "—"),
                            _or(p.get('system') or p.get('target') or p.get('source'), "—"),
                            _or(p.get('purpose'), "—"),
                            _or(
                                p.get('information_exchanged')
                                or p.get('payload_summary'),
                                "—",
                            ),
                            _or(
                                p.get('trigger')
                                or p.get('timing')
                                or p.get('frequency'),
                                "—",
                            ),
                            _or(p.get('related_step') or p.get('step_id'), "—"),
                        ])
                    else:
                        rows.append([str(p), "—", "—", "—", "—", "—"])
                self._add_data_table(
                    doc,
                    [
                        "Integration", "System", "Purpose",
                        "Information Exchanged", "Trigger / Timing",
                        "Related Step",
                    ],
                    rows,
                )
            else:
                self._add_bullet_list(doc, integration_points)

        process_exceptions = pm.get('exceptions') or []
        if process_exceptions:
            doc.add_heading(f"{section_num}. Exceptions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Process-level exceptions identified in the source data. "
                "Step-level exceptions are recorded in the Step Details "
                "section above."
            )
            self._add_bullet_list(doc, process_exceptions)

        process_controls = pm.get('controls') or []
        if process_controls:
            doc.add_heading(f"{section_num}. Controls", level=1)
            section_num += 1
            has_structured_controls = any(isinstance(c, dict) for c in process_controls)
            if has_structured_controls:
                rows = []
                for c in process_controls:
                    if isinstance(c, dict):
                        rows.append([
                            _or(c.get('control'), "—"),
                            _or(c.get('purpose'), "—"),
                            _or(c.get('responsible_role') or c.get('role'), "—"),
                            _or(c.get('process_step') or c.get('step_id'), "—"),
                        ])
                    else:
                        rows.append([str(c), "—", "—", "—"])
                self._add_data_table(
                    doc,
                    ["Control", "Purpose", "Responsible Role", "Process Step"],
                    rows,
                )
            else:
                self._add_bullet_list(doc, process_controls)

        improvements = pm.get('improvements') or []
        if improvements:
            doc.add_heading(f"{section_num}. Identified Improvements", level=1)
            section_num += 1
            has_structured_imp = any(isinstance(i, dict) for i in improvements)
            if has_structured_imp:
                rows = []
                for i in improvements:
                    if isinstance(i, dict):
                        rows.append([
                            _or(i.get('improvement') or i.get('description'), "—"),
                            _or(i.get('rationale') or i.get('business_rationale'), "—"),
                            _or(i.get('affected_step') or i.get('step_id'), "—"),
                            _or(i.get('expected_outcome'), "—"),
                            _or(i.get('priority'), "—"),
                        ])
                    else:
                        rows.append([str(i), "—", "—", "—", "—"])
                self._add_data_table(
                    doc,
                    [
                        "Improvement", "Business Rationale",
                        "Affected Step", "Expected Outcome", "Priority",
                    ],
                    rows,
                )
            else:
                self._add_bullet_list(doc, improvements)

        open_qs = pm.get('open_questions') or []
        if open_qs:
            doc.add_heading(f"{section_num}. Open Questions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Open questions remain unresolved. Blocking items must be "
                "resolved before the affected steps or requirements can be "
                "confirmed."
            )
            rows = []
            for q in open_qs:
                if isinstance(q, dict):
                    rows.append([
                        _or(q.get('question'), "—"),
                        _or(q.get('context') or q.get('topic'), ""),
                        _or(q.get('owner'), ""),
                        "Yes" if q.get('blocking') else "No",
                    ])
                else:
                    rows.append([str(q), "", "", "No"])
            self._add_data_table(
                doc,
                ["Question", "Context", "Owner", "Blocking"],
                rows,
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
        if test_type == "QA":
            return self._generate_qa_test_case_document_qa(
                project_name, module, test_cases, session_id,
            )
        return self._generate_uat_test_case_document(
            project_name, module, test_cases, test_type, session_id,
        )

    def _generate_qa_test_case_document_qa(
        self,
        project_name: str,
        module: str,
        test_cases: List[Dict[str, Any]],
        session_id: Optional[str],
    ) -> str:
        doc = self._new_document("QA Test Case Specification", project_name)
        tcs = list(test_cases or [])

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "—") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _tid(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('id') or tc.get('external_code')) or "To be assigned"

        def _status_raw(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('execution_status') or tc.get('status'))

        def _status_display(tc: Dict[str, Any]) -> str:
            raw = _status_raw(tc)
            if not raw or raw.lower() in ("not_run", "not run", "not-run", "notrun"):
                return "Not Executed"
            return raw

        def _status_bucket(tc: Dict[str, Any]) -> str:
            raw = _status_raw(tc).lower()
            if not raw or raw in ("not_run", "not run", "not-run", "notrun"):
                return "not_executed"
            if raw in ("pass", "passed"):
                return "passed"
            if raw in ("fail", "failed"):
                return "failed"
            if raw == "blocked":
                return "blocked"
            return "other"

        def _actual_result(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('actual_result')
                or tc.get('execution_result')
                or tc.get('actual_outcome')
            ) or "To be completed during execution"

        def _defect_ref(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('defect_id')
                or tc.get('defect_reference')
                or tc.get('issue_id')
            )

        def _tester(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('tester') or tc.get('executed_by'))

        def _execution_date(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('execution_date') or tc.get('tested_on'))

        def _req_ids(tc: Dict[str, Any]) -> List[str]:
            v = tc.get('related_requirement_ids') or tc.get('requirement_ids') or []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x not in (None, "")]
            s = _clean(v)
            return [s] if s else []

        def _step_ids(tc: Dict[str, Any]) -> List[str]:
            v = tc.get('related_process_step_ids') or tc.get('process_step_ids') or []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x not in (None, "")]
            s = _clean(v)
            return [s] if s else []

        def _design(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('related_design_component'))

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        self._add_info_table(doc, [
            ("Project", project_name),
            ("Module / Functional Area", module),
            ("Document Type", "QA Test Case Specification"),
            ("Test Type", "QA"),
            ("Document Status", "Draft for Test Execution"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading(f"{section_num}. Executive Test Summary", level=1)
        section_num += 1
        counts = {"passed": 0, "failed": 0, "blocked": 0, "not_executed": 0, "other": 0}
        retest_count = 0
        for tc in tcs:
            counts[_status_bucket(tc)] += 1
            if tc.get('needs_retest'):
                retest_count += 1
        doc.add_paragraph(
            "Counts below are calculated from the execution-status values "
            "supplied in the source test-case data."
        )
        self._add_data_table(doc, ["Metric", "Count"], [
            ["Total Test Cases", len(tcs)],
            ["Test Cases Passed", counts["passed"]],
            ["Test Cases Failed", counts["failed"]],
            ["Test Cases Blocked", counts["blocked"]],
            ["Test Cases Not Executed", counts["not_executed"]],
            ["Test Cases Requiring Retest", retest_count],
        ])

        if tcs:
            doc.add_heading(f"{section_num}. Test Case Register", level=1)
            section_num += 1
            doc.add_paragraph(
                "The register below lists every test case in this document. "
                "Detailed execution records appear in the following section."
            )
            register_rows = []
            for tc in tcs:
                req_list = _req_ids(tc)
                step_list = _step_ids(tc)
                register_rows.append([
                    _tid(tc),
                    _or(tc.get('scenario')),
                    _or(tc.get('priority')),
                    _or(tc.get('type'), "Functional"),
                    ", ".join(req_list) if req_list else "—",
                    ", ".join(step_list) if step_list else "—",
                    _or(_design(tc)),
                    _status_display(tc),
                    "Yes" if tc.get('needs_retest') else "No",
                ])
            self._add_data_table(
                doc,
                [
                    "Test Case ID", "Scenario", "Priority", "Test Type",
                    "Requirement Refs", "Process Step Refs", "Design Component",
                    "Status", "Needs Retest",
                ],
                register_rows,
            )

        if tcs:
            doc.add_heading(f"{section_num}. Detailed Test Cases", level=1)
            section_num += 1
            for tc in tcs:
                tid = _tid(tc)
                scenario = _or(tc.get('scenario'), "Test Scenario")
                doc.add_heading(f"{tid} — {scenario}", level=2)

                info_rows = [
                    ("Test Case ID", tid),
                    ("Scenario", scenario),
                    ("Priority", _or(tc.get('priority'))),
                    ("Test Type", _or(tc.get('type'), "Functional")),
                ]
                if _clean(tc.get('business_process')):
                    info_rows.append(("Business Process", tc['business_process']))
                if _clean(tc.get('user_role')):
                    info_rows.append(("User Role", tc['user_role']))
                if _design(tc):
                    info_rows.append(("Design Component", _design(tc)))
                self._add_info_table(doc, info_rows)

                if _clean(tc.get('objective')):
                    doc.add_heading("Objective", level=3)
                    doc.add_paragraph(tc['objective'])

                doc.add_heading("Preconditions", level=3)
                preconds = tc.get('preconditions') or []
                if preconds:
                    self._add_bullet_list(doc, preconds)
                else:
                    doc.add_paragraph("None provided.")

                test_data = tc.get('test_data') or []
                if test_data:
                    doc.add_heading("Test Data", level=3)
                    rows = []
                    for item in test_data:
                        if isinstance(item, dict):
                            rows.append([
                                _or(item.get('key'), ""),
                                _or(item.get('value'), ""),
                            ])
                        else:
                            rows.append([str(item), ""])
                    if rows:
                        self._add_data_table(doc, ["Field", "Value"], rows)

                doc.add_heading("Test Steps", level=3)
                steps = tc.get('steps') or []
                if steps:
                    for step_num, step in enumerate(steps, 1):
                        if isinstance(step, dict):
                            action = _clean(
                                step.get('action')
                                or step.get('step')
                                or step.get('description')
                            )
                            expected = _clean(step.get('expected'))
                            line = f"{step_num}. {action}" if action else f"{step_num}. {step}"
                            doc.add_paragraph(line)
                            if expected:
                                doc.add_paragraph(f"     Expected: {expected}")
                        else:
                            doc.add_paragraph(f"{step_num}. {step}")
                else:
                    doc.add_paragraph("To be completed.")

                doc.add_heading("Expected Result", level=3)
                expected_result = _clean(tc.get('expected_result'))
                doc.add_paragraph(expected_result if expected_result else "To be completed.")

                ac = tc.get('acceptance_criteria')
                if ac:
                    doc.add_heading("Acceptance Criteria", level=3)
                    if isinstance(ac, (list, tuple)):
                        for i, c in enumerate(ac, 1):
                            doc.add_paragraph(f"{i}. {c}")
                    else:
                        doc.add_paragraph(str(ac))

                doc.add_heading("Traceability", level=3)
                req_list = _req_ids(tc)
                step_list = _step_ids(tc)
                design_ref = _design(tc)
                if req_list or step_list or design_ref:
                    if req_list:
                        doc.add_paragraph("Requirement Traceability", style='List Bullet')
                        for r in req_list:
                            doc.add_paragraph(str(r), style='List Bullet 2')
                    if step_list:
                        doc.add_paragraph("Process Traceability", style='List Bullet')
                        for s in step_list:
                            doc.add_paragraph(str(s), style='List Bullet 2')
                    if design_ref:
                        doc.add_paragraph(
                            f"Design Traceability: {design_ref}", style='List Bullet',
                        )
                else:
                    doc.add_paragraph("No traceability provided.")

                doc.add_heading("Execution Result", level=3)
                doc.add_paragraph("Expected Result", style='List Bullet')
                doc.add_paragraph(
                    expected_result if expected_result else "To be completed.",
                    style='List Bullet 2',
                )
                doc.add_paragraph("Actual Result", style='List Bullet')
                doc.add_paragraph(_actual_result(tc), style='List Bullet 2')

                doc.add_heading("Test Status", level=3)
                doc.add_paragraph(_status_display(tc))

                fc = _clean(tc.get('failure_classification'))
                fd = _clean(tc.get('failure_description'))
                if fc or fd:
                    doc.add_heading("Failure Information", level=3)
                    if fc:
                        doc.add_paragraph(f"Failure Classification: {fc}")
                    if fd:
                        doc.add_paragraph(f"Failure Description: {fd}")

                doc.add_heading("Retest Information", level=3)
                doc.add_paragraph(
                    "Needs Retest: " + ("Yes" if tc.get('needs_retest') else "No")
                )
                retest_notes = _clean(tc.get('retest_notes'))
                if retest_notes:
                    doc.add_paragraph(retest_notes)

                evidence = _clean(
                    tc.get('evidence')
                    or tc.get('evidence_reference')
                    or tc.get('notes')
                )
                if evidence:
                    doc.add_heading("Execution Evidence / Notes", level=3)
                    doc.add_paragraph(evidence)

        req_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            for r in _req_ids(tc):
                req_to_tcs.setdefault(r, []).append(tid)
        if req_to_tcs:
            doc.add_heading(f"{section_num}. Requirement Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Requirement-to-test-case relationships are sourced from "
                "the structured test-case data. They are not inferred."
            )
            rows = [[rid, ", ".join(tids)] for rid, tids in req_to_tcs.items()]
            self._add_data_table(
                doc, ["Requirement ID", "Related Test Case IDs"], rows,
            )

        step_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            for s in _step_ids(tc):
                step_to_tcs.setdefault(s, []).append(tid)
        if step_to_tcs:
            doc.add_heading(f"{section_num}. Process Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Process-step-to-test-case relationships are sourced from "
                "the structured test-case data. They are not inferred."
            )
            rows = [[sid, ", ".join(tids)] for sid, tids in step_to_tcs.items()]
            self._add_data_table(
                doc, ["Process Step ID", "Related Test Case IDs"], rows,
            )

        design_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            d = _design(tc)
            if d:
                design_to_tcs.setdefault(d, []).append(tid)
        if design_to_tcs:
            doc.add_heading(f"{section_num}. Design Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Design-component-to-test-case relationships are sourced "
                "from the structured test-case data. They are not inferred."
            )
            rows = [[d, ", ".join(tids)] for d, tids in design_to_tcs.items()]
            self._add_data_table(
                doc,
                ["Design Component / Decision ID", "Related Test Case IDs"],
                rows,
            )

        defect_rows = []
        for tc in tcs:
            fc = _clean(tc.get('failure_classification'))
            fd = _clean(tc.get('failure_description'))
            if fc or fd:
                defect_rows.append([
                    _tid(tc),
                    _defect_ref(tc) or "—",
                    fc or "—",
                    fd or "—",
                    _status_display(tc),
                    "Yes" if tc.get('needs_retest') else "No",
                ])
        if defect_rows:
            doc.add_heading(f"{section_num}. Defect Summary", level=1)
            section_num += 1
            doc.add_paragraph(
                "The table below consolidates the failure and defect "
                "information recorded against individual test cases. "
                "Defect references are shown only where the source supplies "
                "one."
            )
            self._add_data_table(
                doc,
                [
                    "Test Case ID", "Defect Reference", "Failure Classification",
                    "Failure Description", "Status", "Needs Retest",
                ],
                defect_rows,
            )

        retest_rows = []
        for tc in tcs:
            if tc.get('needs_retest'):
                retest_rows.append([
                    _tid(tc),
                    _clean(tc.get('failure_classification')) or "—",
                    _clean(tc.get('failure_description')) or "—",
                ])
        if retest_rows:
            doc.add_heading(f"{section_num}. Retest Required", level=1)
            section_num += 1
            doc.add_paragraph(
                "The test cases below are marked for retest in the source "
                "data. Retest dates and outcomes are not recorded here "
                "unless the source supplies them."
            )
            self._add_data_table(
                doc,
                ["Test Case ID", "Failure Classification", "Failure Description"],
                retest_rows,
            )

        if tcs:
            doc.add_heading(f"{section_num}. Test Execution Summary", level=1)
            section_num += 1
            exec_rows = []
            for tc in tcs:
                exec_rows.append([
                    _tid(tc),
                    _or(tc.get('scenario')),
                    _or(tc.get('priority')),
                    _status_display(tc),
                    _actual_result(tc),
                    _defect_ref(tc) or "—",
                    "Yes" if tc.get('needs_retest') else "No",
                    _tester(tc) or "To be completed",
                    _execution_date(tc) or "To be completed",
                ])
            self._add_data_table(
                doc,
                [
                    "Test Case ID", "Scenario", "Priority", "Status",
                    "Actual Result", "Defect Reference", "Needs Retest",
                    "Tester", "Execution Date",
                ],
                exec_rows,
            )

        filepath = self._save(
            doc, "test_cases_QA", project_name, session_id=session_id,
            phase="qa_testing", label="qa_testing",
        )
        self.logger.log_tool_usage(
            "generate_test_case_document",
            {'project': project_name, 'test_type': "QA"},
            f"Document saved to {filepath}",
        )
        return filepath

    def _generate_uat_test_case_document(
        self,
        project_name: str,
        module: str,
        test_cases: List[Dict[str, Any]],
        test_type: str,
        session_id: Optional[str],
    ) -> str:
        doc = self._new_document("User Acceptance Test Specification", project_name)
        tcs = list(test_cases or [])

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "—") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _tid(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('id') or tc.get('external_code')) or "To be assigned"

        def _business_process(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('business_process')
                or tc.get('process_name')
                or tc.get('process')
            )

        def _user_role(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('user_role')
                or tc.get('business_role')
                or tc.get('role')
            )

        def _business_objective(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('business_objective')
                or tc.get('objective')
            )

        def _expected_outcome(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('expected_business_outcome')
                or tc.get('expected_result')
                or tc.get('expected_outcome')
            )

        def _actual_result(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('actual_result')
                or tc.get('execution_result')
                or tc.get('actual_outcome')
            ) or "To be completed during execution"

        def _status_raw(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('execution_status') or tc.get('status'))

        def _status_display(tc: Dict[str, Any]) -> str:
            raw = _status_raw(tc)
            if not raw or raw.lower() in ("not_run", "not run", "not-run", "notrun"):
                return "To be completed"
            return raw

        def _status_bucket(tc: Dict[str, Any]) -> str:
            raw = _status_raw(tc).lower()
            if not raw or raw in ("not_run", "not run", "not-run", "notrun"):
                return "not_executed"
            if raw in ("pass", "passed"):
                return "passed"
            if raw in ("fail", "failed"):
                return "failed"
            if raw == "blocked":
                return "blocked"
            if raw == "accepted":
                return "accepted"
            if raw == "rejected":
                return "rejected"
            return "other"

        def _acceptance_decision(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('acceptance_decision')
                or tc.get('business_acceptance')
                or tc.get('acceptance_status')
            )

        def _defect_ref(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('defect_id')
                or tc.get('defect_reference')
                or tc.get('issue_id')
            )

        def _tester(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('tester') or tc.get('executed_by'))

        def _execution_date(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('execution_date') or tc.get('tested_on'))

        def _req_ids(tc: Dict[str, Any]) -> List[str]:
            v = tc.get('related_requirement_ids') or tc.get('requirement_ids') or []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x not in (None, "")]
            s = _clean(v)
            return [s] if s else []

        def _step_ids(tc: Dict[str, Any]) -> List[str]:
            v = tc.get('related_process_step_ids') or tc.get('process_step_ids') or []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x not in (None, "")]
            s = _clean(v)
            return [s] if s else []

        def _design(tc: Dict[str, Any]) -> str:
            return _clean(tc.get('related_design_component'))

        def _evidence(tc: Dict[str, Any]) -> str:
            return _clean(
                tc.get('evidence')
                or tc.get('evidence_reference')
                or tc.get('notes')
            )

        def _acceptance_criteria_list(tc: Dict[str, Any]) -> List[str]:
            ac = tc.get('acceptance_criteria')
            if ac is None:
                return []
            if isinstance(ac, (list, tuple)):
                return [str(c) for c in ac if c is not None and str(c).strip()]
            s = str(ac).strip()
            return [s] if s else []

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        info_rows = [
            ("Project", project_name),
            ("Module / Functional Area", module),
        ]
        erp_system_candidates = [
            _clean(tc.get('erp_system')) for tc in tcs
            if isinstance(tc, dict)
        ]
        erp_system = next((e for e in erp_system_candidates if e), "")
        if erp_system:
            info_rows.append(("ERP System", erp_system))
        info_rows.extend([
            ("Document Type", "User Acceptance Test Specification"),
            ("Test Type", test_type),
            ("UAT Status", "Draft for UAT Execution"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])
        self._add_info_table(doc, info_rows)

        bp_to_tcs: Dict[str, List[str]] = {}
        bp_to_roles: Dict[str, set] = {}
        for tc in tcs:
            bp = _business_process(tc)
            if not bp:
                continue
            tid = _tid(tc)
            bp_to_tcs.setdefault(bp, []).append(tid)
            role = _user_role(tc)
            if role:
                bp_to_roles.setdefault(bp, set()).add(role)
        if bp_to_tcs:
            doc.add_heading(f"{section_num}. Business Process and Role Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Business processes and the user roles that validate them, "
                "as supplied by the source UAT data."
            )
            rows = []
            for bp, tids in bp_to_tcs.items():
                roles = sorted(bp_to_roles.get(bp, set()))
                rows.append([bp, ", ".join(tids), ", ".join(roles) if roles else "—"])
            self._add_data_table(
                doc,
                ["Business Process", "Related Test Case IDs", "User Roles"],
                rows,
            )

        if tcs:
            doc.add_heading(f"{section_num}. Test Case Register", level=1)
            section_num += 1
            doc.add_paragraph(
                "Summary of every UAT case in this document. Detailed "
                "execution records appear in the following section."
            )
            register_rows = []
            for tc in tcs:
                req_list = _req_ids(tc)
                step_list = _step_ids(tc)
                register_rows.append([
                    _tid(tc),
                    _or(tc.get('scenario')),
                    _or(_business_process(tc)),
                    _or(_user_role(tc)),
                    _or(tc.get('priority')),
                    ", ".join(req_list) if req_list else "—",
                    ", ".join(step_list) if step_list else "—",
                    _or(_design(tc)),
                    _status_display(tc),
                    "Yes" if tc.get('needs_retest') else "No",
                ])
            self._add_data_table(
                doc,
                [
                    "Test Case ID", "Scenario", "Business Process", "User Role",
                    "Priority", "Requirement Refs", "Process Step Refs",
                    "Design Component", "Status", "Needs Retest",
                ],
                register_rows,
            )

        if tcs:
            doc.add_heading(f"{section_num}. Detailed UAT Test Cases", level=1)
            section_num += 1
            for tc in tcs:
                tid = _tid(tc)
                scenario = _or(tc.get('scenario'), "UAT Scenario")
                doc.add_heading(f"{tid} — {scenario}", level=2)

                info_rows = [
                    ("Test Case ID", tid),
                    ("Scenario", scenario),
                ]
                bp = _business_process(tc)
                if bp:
                    info_rows.append(("Business Process", bp))
                role = _user_role(tc)
                if role:
                    info_rows.append(("User Role", role))
                biz_obj = _business_objective(tc)
                if biz_obj:
                    info_rows.append(("Business Objective", biz_obj))
                info_rows.append(("Priority", _or(tc.get('priority'))))
                info_rows.append(("Test Type", _or(tc.get('type'), "Functional")))
                if _design(tc):
                    info_rows.append(("Design Component", _design(tc)))
                self._add_info_table(doc, info_rows)

                doc.add_heading("Preconditions", level=3)
                preconds = tc.get('preconditions') or []
                if preconds:
                    self._add_bullet_list(doc, preconds)
                else:
                    doc.add_paragraph("None provided.")

                test_data = tc.get('test_data') or []
                if test_data:
                    doc.add_heading("Test Data", level=3)
                    rows = []
                    for item in test_data:
                        if isinstance(item, dict):
                            rows.append([
                                _or(item.get('key'), ""),
                                _or(item.get('value'), ""),
                            ])
                        else:
                            rows.append([str(item), ""])
                    if rows:
                        self._add_data_table(doc, ["Field", "Value"], rows)

                doc.add_heading("Test Steps", level=3)
                steps = tc.get('steps') or []
                if steps:
                    for step_num, step in enumerate(steps, 1):
                        if isinstance(step, dict):
                            action = _clean(
                                step.get('action')
                                or step.get('step')
                                or step.get('description')
                            )
                            expected = _clean(
                                step.get('expected')
                                or step.get('expected_outcome')
                            )
                            line = f"{step_num}. {action}" if action else f"{step_num}. {step}"
                            doc.add_paragraph(line)
                            if expected:
                                doc.add_paragraph(f"     Expected: {expected}")
                        else:
                            doc.add_paragraph(f"{step_num}. {step}")
                else:
                    doc.add_paragraph("To be completed.")

                doc.add_heading("Expected Business Outcome", level=3)
                expected = _expected_outcome(tc)
                doc.add_paragraph(expected if expected else "To be completed.")

                doc.add_heading("Acceptance Criteria", level=3)
                ac_list = _acceptance_criteria_list(tc)
                if ac_list:
                    for i, criterion in enumerate(ac_list, 1):
                        doc.add_paragraph(f"{i}. {criterion}")
                else:
                    doc.add_paragraph("To be confirmed")

                doc.add_heading("Traceability", level=3)
                req_list = _req_ids(tc)
                step_list = _step_ids(tc)
                design_ref = _design(tc)
                if req_list or step_list or design_ref:
                    if req_list:
                        doc.add_paragraph("Requirement Traceability", style='List Bullet')
                        for r in req_list:
                            doc.add_paragraph(str(r), style='List Bullet 2')
                    if step_list:
                        doc.add_paragraph("Process Traceability", style='List Bullet')
                        for s in step_list:
                            doc.add_paragraph(str(s), style='List Bullet 2')
                    if design_ref:
                        doc.add_paragraph(
                            f"Design Traceability: {design_ref}", style='List Bullet',
                        )
                else:
                    doc.add_paragraph("No traceability provided.")

                doc.add_heading("Execution Result", level=3)
                doc.add_paragraph("Expected Business Outcome", style='List Bullet')
                doc.add_paragraph(
                    expected if expected else "To be completed.",
                    style='List Bullet 2',
                )
                doc.add_paragraph("Actual Result", style='List Bullet')
                doc.add_paragraph(_actual_result(tc), style='List Bullet 2')

                doc.add_heading("UAT Status", level=3)
                doc.add_paragraph(_status_display(tc))

                decision = _acceptance_decision(tc)
                if decision:
                    doc.add_heading("Business Acceptance Decision", level=3)
                    doc.add_paragraph(decision)

                fc = _clean(tc.get('failure_classification'))
                fd = _clean(tc.get('failure_description'))
                dref = _defect_ref(tc)
                if fc or fd or dref:
                    doc.add_heading("Defect / Issue", level=3)
                    if dref:
                        doc.add_paragraph(f"Defect Reference: {dref}")
                    if fc:
                        doc.add_paragraph(f"Failure Classification: {fc}")
                    if fd:
                        doc.add_paragraph(f"Failure Description: {fd}")

                doc.add_heading("Retest Information", level=3)
                doc.add_paragraph(
                    "Needs Retest: " + ("Yes" if tc.get('needs_retest') else "No")
                )
                retest_notes = _clean(tc.get('retest_notes'))
                if retest_notes:
                    doc.add_paragraph(retest_notes)

                ev = _evidence(tc)
                if ev:
                    doc.add_heading("Evidence / Notes", level=3)
                    doc.add_paragraph(ev)

                doc.add_heading("Execution Record", level=3)
                self._add_info_table(doc, [
                    ("Tester", _tester(tc) or "To be completed"),
                    ("Execution Date", _execution_date(tc) or "To be completed"),
                ])

        req_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            for r in _req_ids(tc):
                req_to_tcs.setdefault(r, []).append(tid)
        if req_to_tcs:
            doc.add_heading(f"{section_num}. Requirement Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Requirement-to-UAT-case relationships are sourced from the "
                "structured UAT data. They are not inferred."
            )
            rows = [[rid, ", ".join(tids)] for rid, tids in req_to_tcs.items()]
            self._add_data_table(
                doc, ["Requirement ID", "Related UAT Test Case IDs"], rows,
            )

        step_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            for s in _step_ids(tc):
                step_to_tcs.setdefault(s, []).append(tid)
        if step_to_tcs:
            doc.add_heading(f"{section_num}. Process Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Process-step-to-UAT-case relationships are sourced from the "
                "structured UAT data. They are not inferred."
            )
            rows = [[sid, ", ".join(tids)] for sid, tids in step_to_tcs.items()]
            self._add_data_table(
                doc, ["Process Step ID", "Related UAT Test Case IDs"], rows,
            )

        design_to_tcs: Dict[str, List[str]] = {}
        for tc in tcs:
            tid = _tid(tc)
            d = _design(tc)
            if d:
                design_to_tcs.setdefault(d, []).append(tid)
        if design_to_tcs:
            doc.add_heading(f"{section_num}. Solution Design Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "Design-component-to-UAT-case relationships are sourced "
                "from the structured UAT data. They are not inferred."
            )
            rows = [[d, ", ".join(tids)] for d, tids in design_to_tcs.items()]
            self._add_data_table(
                doc,
                ["Design Component / Decision ID", "Related UAT Test Case IDs"],
                rows,
            )

        defect_rows = []
        for tc in tcs:
            fc = _clean(tc.get('failure_classification'))
            fd = _clean(tc.get('failure_description'))
            dref = _defect_ref(tc)
            if fc or fd or dref:
                defect_rows.append([
                    _tid(tc),
                    dref or "—",
                    fd or fc or "—",
                    _status_display(tc),
                    "Yes" if tc.get('needs_retest') else "No",
                ])
        if defect_rows:
            doc.add_heading(f"{section_num}. Defect and Issue Summary", level=1)
            section_num += 1
            doc.add_paragraph(
                "The table below consolidates defect and issue information "
                "recorded against individual UAT cases. Defect references "
                "are shown only where the source supplies one."
            )
            self._add_data_table(
                doc,
                [
                    "Test Case ID", "Defect / Issue Reference",
                    "Description", "Status", "Needs Retest",
                ],
                defect_rows,
            )

        retest_rows = []
        for tc in tcs:
            if tc.get('needs_retest'):
                retest_rows.append([
                    _tid(tc),
                    _defect_ref(tc) or "—",
                    _clean(tc.get('failure_description'))
                        or _clean(tc.get('failure_classification'))
                        or "—",
                ])
        if retest_rows:
            doc.add_heading(f"{section_num}. Retest Required", level=1)
            section_num += 1
            doc.add_paragraph(
                "The UAT cases below are marked for retest in the source "
                "data. Retest dates, testers, and outcomes are not recorded "
                "here unless the source supplies them."
            )
            self._add_data_table(
                doc,
                ["Test Case ID", "Defect / Issue Reference", "Description"],
                retest_rows,
            )

        counts = {"passed": 0, "failed": 0, "blocked": 0, "not_executed": 0,
                  "accepted": 0, "rejected": 0, "other": 0}
        retest_count = 0
        for tc in tcs:
            counts[_status_bucket(tc)] += 1
            if tc.get('needs_retest'):
                retest_count += 1
        has_explicit_acceptance = counts["accepted"] > 0 or counts["rejected"] > 0
        doc.add_heading(f"{section_num}. UAT Acceptance Summary", level=1)
        section_num += 1
        doc.add_paragraph(
            "Counts below are calculated from the status values supplied in "
            "the source UAT data. Where a status is absent, the case is "
            "counted as Not Executed; it is not classified as Passed or "
            "Failed."
        )
        summary_rows = [
            ["Total Test Cases", len(tcs)],
            ["Passed", counts["passed"]],
            ["Failed", counts["failed"]],
            ["Blocked", counts["blocked"]],
            ["Not Executed", counts["not_executed"]],
            ["Requiring Retest", retest_count],
        ]
        if has_explicit_acceptance:
            summary_rows.append(["Accepted", counts["accepted"]])
            summary_rows.append(["Rejected", counts["rejected"]])
        self._add_data_table(doc, ["Metric", "Count"], summary_rows)

        doc.add_heading(f"{section_num}. UAT Review and Sign-off", level=1)
        section_num += 1
        doc.add_paragraph(
            "This section supports business review and sign-off. Fields "
            "marked 'To be completed' remain outstanding. This document "
            "does not itself constitute approval."
        )
        self._add_data_table(
            doc,
            ["Business Owner / Approver", "Role", "Decision", "Date", "Comments"],
            [
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
            ],
        )

        filepath = self._save(
            doc, f"test_cases_{test_type}", project_name, session_id=session_id,
            phase="uat_testing", label="uat_testing",
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
        doc = self._new_document("ERP User Manual", module)
        steps = list(process_steps or [])

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "To be completed") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _as_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [str(v) for v in value if v is not None and str(v).strip()]
            s = str(value).strip()
            return [s] if s else []

        def _step_dict(step: Any) -> Dict[str, Any]:
            return step if isinstance(step, dict) else {}

        def _canonical_id(step: Any) -> str:
            return _clean(_step_dict(step).get('id'))

        def _canonical_number(step: Any) -> str:
            d = _step_dict(step)
            num = d.get('number')
            if num in (None, ""):
                return ""
            return str(num)

        def _step_display_name(step: Any) -> str:
            d = _step_dict(step)
            return (
                _clean(d.get('title'))
                or _clean(d.get('name'))
                or _clean(step)
                or "Process Step"
            )

        def _step_heading(step: Any, idx: int) -> str:
            cid = _canonical_id(step)
            cnum = _canonical_number(step)
            name = _step_display_name(step)
            if cid:
                return f"{cid} | {name}"
            if cnum:
                return f"Step {cnum}: {name}"
            return f"Step {idx + 1}: {name}"

        def _step_role(step: Any) -> str:
            d = _step_dict(step)
            return _clean(d.get('role') or d.get('responsible_role'))

        def _step_transaction(step: Any) -> str:
            d = _step_dict(step)
            return _clean(d.get('transaction'))

        def _step_purpose(step: Any) -> str:
            d = _step_dict(step)
            return _clean(d.get('purpose'))

        def _step_description(step: Any) -> str:
            return _clean(_step_dict(step).get('description'))

        def _step_before_you_start(step: Any) -> List[str]:
            d = _step_dict(step)
            v = d.get('before_you_start')
            if v is None:
                v = d.get('preconditions')
            return _as_list(v)

        def _step_instructions(step: Any) -> List[str]:
            d = _step_dict(step)
            v = d.get('instructions')
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x is not None and str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _step_fields(step: Any) -> List[Any]:
            d = _step_dict(step)
            v = d.get('fields')
            if v is None:
                v = d.get('key_fields')
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [x for x in v if x is not None]
            return [v]

        def _step_expected_outcome(step: Any) -> str:
            d = _step_dict(step)
            v = (
                d.get('expected_outcome')
                or d.get('expected_result')
            )
            if v:
                return _clean(v)
            outs = d.get('outputs')
            if isinstance(outs, (list, tuple)):
                outs = [str(o) for o in outs if o is not None and str(o).strip()]
                if outs:
                    return "; ".join(outs)
            elif _clean(outs):
                return _clean(outs)
            return ""

        def _step_verification(step: Any) -> str:
            return _clean(_step_dict(step).get('verification'))

        def _step_common_issues(step: Any) -> List[Any]:
            d = _step_dict(step)
            v = d.get('common_issues')
            if v is None:
                v = d.get('common_errors')
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [x for x in v if x is not None]
            return [v]

        def _step_tips(step: Any) -> List[str]:
            d = _step_dict(step)
            v = d.get('tips')
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v if x is not None and str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _step_requirement_ids(step: Any) -> List[str]:
            d = _step_dict(step)
            ids: List[str] = []
            for key in ('requirement_id', 'related_requirement_ids', 'requirement_ids'):
                v = d.get(key)
                if v in (None, "", []):
                    continue
                if isinstance(v, (list, tuple)):
                    ids.extend(str(x) for x in v if x not in (None, ""))
                else:
                    ids.append(str(v))
            seen = set()
            out: List[str] = []
            for x in ids:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        step_records: List[Dict[str, Any]] = []
        for i, s in enumerate(steps):
            step_records.append({
                'idx': i,
                'raw': s,
                'id': _canonical_id(s),
                'number': _canonical_number(s),
                'name': _step_display_name(s),
                'role': _step_role(s),
                'transaction': _step_transaction(s),
                'purpose': _step_purpose(s),
                'description': _step_description(s),
                'before_you_start': _step_before_you_start(s),
                'instructions': _step_instructions(s),
                'fields': _step_fields(s),
                'expected_outcome': _step_expected_outcome(s),
                'verification': _step_verification(s),
                'common_issues': _step_common_issues(s),
                'tips': _step_tips(s),
                'requirement_ids': _step_requirement_ids(s),
            })

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        self._add_info_table(doc, [
            ("Module / Functional Area", module),
            ("Business Process", process_name),
            ("Document Type", "ERP User Manual"),
            ("Document Status", "Draft for Review"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        doc.add_heading(f"{section_num}. Purpose", level=1)
        section_num += 1
        doc.add_paragraph(
            f"This manual guides the user through the steps required to "
            f"execute the {process_name} process in the {module} module."
        )

        doc.add_heading(f"{section_num}. Learning Objectives", level=1)
        section_num += 1
        doc.add_paragraph(
            "By the end of this manual, the reader is expected to be able "
            "to complete each step of the process using the supplied "
            "instructions, verify successful completion, and recognise the "
            "most common issues. Specific learning objectives: To be confirmed."
        )

        all_prereqs: List[str] = []
        for rec in step_records:
            for p in rec['before_you_start']:
                if p not in all_prereqs:
                    all_prereqs.append(p)
        doc.add_heading(f"{section_num}. Prerequisites", level=1)
        section_num += 1
        if all_prereqs:
            doc.add_paragraph(
                "Prerequisites that apply to the process are listed below. "
                "Any additional step-specific prerequisites are shown in "
                "the 'Before You Start' subsection of the relevant step."
            )
            self._add_bullet_list(doc, all_prereqs)
        else:
            doc.add_paragraph("No prerequisites provided.")

        if len(step_records) >= 2:
            doc.add_heading(f"{section_num}. Quick Reference", level=1)
            section_num += 1
            doc.add_paragraph(
                "The table below provides a compact view of the steps, the "
                "responsible user role, the transaction or activity, and "
                "the step purpose (where supplied)."
            )
            rows = []
            for rec in step_records:
                step_label = rec['id'] or rec['number'] or str(rec['idx'] + 1)
                rows.append([
                    step_label,
                    rec['name'],
                    rec['role'] or "To be completed",
                    rec['transaction'] or "—",
                    rec['purpose'] or "—",
                ])
            self._add_data_table(
                doc,
                ["Step ID", "Step", "User Role", "Transaction", "Purpose"],
                rows,
            )

        if step_records:
            doc.add_heading(f"{section_num}. Step-by-Step Instructions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Steps are presented in process sequence. The identity of "
                "each step matches the Process Map so it can be located by "
                "the same reference downstream."
            )
            for rec in step_records:
                doc.add_heading(_step_heading(rec['raw'], rec['idx']), level=2)

                info_rows = []
                if rec['role']:
                    info_rows.append(("Responsible Role", rec['role']))
                if rec['transaction']:
                    info_rows.append(("Transaction / Activity", rec['transaction']))
                if rec['purpose']:
                    info_rows.append(("Purpose", rec['purpose']))
                if info_rows:
                    self._add_info_table(doc, info_rows)

                if rec['description']:
                    doc.add_heading("Description", level=3)
                    doc.add_paragraph(rec['description'])

                step_prereqs = rec['before_you_start']
                unique_prereqs = [p for p in step_prereqs if p not in all_prereqs]
                if unique_prereqs:
                    doc.add_heading("Before You Start", level=3)
                    self._add_bullet_list(doc, unique_prereqs)

                doc.add_heading("Instructions", level=3)
                if rec['instructions']:
                    for step_idx, instr in enumerate(rec['instructions'], 1):
                        doc.add_paragraph(f"{step_idx}. {instr}")
                else:
                    doc.add_paragraph("To be completed.")

                if rec['fields']:
                    doc.add_heading("Key Fields", level=3)
                    rows = []
                    for f in rec['fields']:
                        if isinstance(f, dict):
                            rows.append([
                                _clean(f.get('name')) or "—",
                                _clean(f.get('required') or f.get('requiredness')) or "—",
                                _clean(f.get('description') or f.get('purpose')) or "—",
                                _clean(f.get('example')) or "—",
                            ])
                        else:
                            rows.append([str(f), "—", "—", "—"])
                    if rows:
                        self._add_data_table(
                            doc,
                            ["Field", "Required / Optional", "Purpose", "Example"],
                            rows,
                        )

                if rec['expected_outcome']:
                    doc.add_heading("Expected Outcome", level=3)
                    doc.add_paragraph(rec['expected_outcome'])

                doc.add_heading("How to Verify", level=3)
                if rec['verification']:
                    doc.add_paragraph(rec['verification'])
                else:
                    doc.add_paragraph("To be confirmed.")

                if rec['common_issues']:
                    doc.add_heading("Common Issues", level=3)
                    rows = []
                    for ci in rec['common_issues']:
                        if isinstance(ci, dict):
                            rows.append([
                                _clean(ci.get('symptom') or ci.get('issue')) or "—",
                                _clean(ci.get('likely_cause') or ci.get('cause')) or "—",
                                _clean(ci.get('resolution') or ci.get('user_action')
                                       or ci.get('action')) or "—",
                            ])
                        else:
                            rows.append([str(ci), "—", "—"])
                    if rows:
                        self._add_data_table(
                            doc,
                            ["Issue", "Likely Cause", "User Action"],
                            rows,
                        )

                if rec['tips']:
                    doc.add_heading("Tips", level=3)
                    self._add_bullet_list(doc, rec['tips'])

                if rec['requirement_ids']:
                    doc.add_heading("Traceability", level=3)
                    doc.add_paragraph(
                        "Requirement References: "
                        + ", ".join(rec['requirement_ids'])
                    )

        trace_rows = []
        for rec in step_records:
            if rec['requirement_ids']:
                step_id = rec['id'] or rec['number'] or str(rec['idx'] + 1)
                trace_rows.append([
                    step_id,
                    rec['name'],
                    ", ".join(rec['requirement_ids']),
                ])
        if trace_rows:
            doc.add_heading(f"{section_num}. Process Traceability", level=1)
            section_num += 1
            doc.add_paragraph(
                "The table below lists the process steps whose source data "
                "explicitly references a requirement. Links are not inferred."
            )
            self._add_data_table(
                doc,
                ["Step ID", "Step Name", "Related Requirement IDs"],
                trace_rows,
            )

        issue_rows = []
        for rec in step_records:
            step_id = rec['id'] or rec['number'] or str(rec['idx'] + 1)
            for ci in rec['common_issues']:
                if isinstance(ci, dict):
                    issue_rows.append([
                        step_id,
                        _clean(ci.get('symptom') or ci.get('issue')) or "—",
                        _clean(ci.get('likely_cause') or ci.get('cause')) or "—",
                        _clean(ci.get('resolution') or ci.get('user_action')
                               or ci.get('action')) or "—",
                    ])
                else:
                    issue_rows.append([step_id, str(ci), "—", "—"])
        if issue_rows:
            doc.add_heading(f"{section_num}. Common Issues and Guidance", level=1)
            section_num += 1
            doc.add_paragraph(
                "The table below consolidates the common issues recorded "
                "against individual steps. Causes and user actions are "
                "shown only where the source supplies them."
            )
            self._add_data_table(
                doc,
                ["Step", "Issue", "Likely Cause", "User Action"],
                issue_rows,
            )

        tip_rows: List[List[str]] = []
        for rec in step_records:
            step_id = rec['id'] or rec['number'] or str(rec['idx'] + 1)
            for t in rec['tips']:
                tip_rows.append([step_id, t])
        if tip_rows:
            doc.add_heading(f"{section_num}. Quick Tips", level=1)
            section_num += 1
            self._add_data_table(doc, ["Step", "Tip"], tip_rows)

        doc.add_heading(f"{section_num}. Support / Escalation", level=1)
        section_num += 1
        doc.add_paragraph(
            "Support and escalation details to be confirmed."
        )

        doc.add_heading(f"{section_num}. Document Review", level=1)
        section_num += 1
        doc.add_paragraph(
            "This manual is a draft for review. Fields marked 'To be "
            "completed' remain outstanding. Completion of this review "
            "does not itself constitute approval of the underlying process."
        )
        self._add_data_table(
            doc,
            ["Reviewer", "Role", "Review Status", "Review Date", "Comments"],
            [
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
            ],
        )

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
        doc = self._new_document(
            "ERP Solution Design Specification",
            project_name,
        )
        des = design or {}

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "Not provided") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _as_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [str(v) for v in value if v is not None and str(v).strip()]
            s = str(value).strip()
            return [s] if s else []

        def _collect_refs(item: Any, keys: tuple) -> List[str]:
            if not isinstance(item, dict):
                return []
            ids: List[str] = []
            for key in keys:
                v = item.get(key)
                if v in (None, "", []):
                    continue
                if isinstance(v, (list, tuple)):
                    ids.extend(str(x) for x in v if x not in (None, ""))
                else:
                    ids.append(str(v))
            seen = set()
            out: List[str] = []
            for x in ids:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        def _requirement_refs(item: Any) -> List[str]:
            return _collect_refs(
                item,
                ('requirement_id', 'related_requirement_ids', 'requirement_ids'),
            )

        def _process_refs(item: Any) -> List[str]:
            return _collect_refs(
                item,
                ('process_step_ids', 'related_process_step_ids',
                 'step_id', 'process_step'),
            )

        def _decision_code(item: Any) -> str:
            if isinstance(item, dict):
                for key in ('external_code', 'id'):
                    v = _clean(item.get(key))
                    if v:
                        return v
            return ""

        def _decision_heading(item: Any, fallback: str = "Decision") -> str:
            code = _decision_code(item)
            if code:
                return code
            if isinstance(item, dict):
                name = _clean(item.get('component') or item.get('name'))
                if name:
                    return name
            return fallback

        section_num = 1

        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        info_rows = [
            ("Project", project_name),
            ("Module / Functional Area", module),
        ]
        erp_system = _clean(des.get('erp_system'))
        if erp_system:
            info_rows.append(("ERP System", erp_system))
        info_rows.extend([
            ("Document Type", "ERP Solution Design Specification"),
            ("Design Status", "Draft for Review"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])
        self._add_info_table(doc, info_rows)

        doc.add_heading(f"{section_num}. Executive Summary", level=1)
        section_num += 1
        doc.add_paragraph(_or(des.get('executive_summary'), "To be confirmed."))

        context = _clean(
            des.get('solution_context')
            or des.get('business_context')
            or des.get('context')
        )
        objectives_list = _as_list(
            des.get('solution_objectives') or des.get('objectives')
        )
        if context or objectives_list:
            doc.add_heading(f"{section_num}. Solution Context", level=1)
            section_num += 1
            if context:
                doc.add_paragraph(context)
            if objectives_list:
                doc.add_heading("Solution Objectives", level=2)
                self._add_bullet_list(doc, objectives_list)

        architecture = _clean(des.get('architecture_overview'))
        if architecture:
            doc.add_heading(f"{section_num}. Solution Architecture", level=1)
            section_num += 1
            doc.add_paragraph(architecture)

        configurations = des.get('configurations') or []
        integrations = des.get('integrations') or []
        customizations = des.get('customizations') or []
        explicit_decisions = des.get('decisions') or []

        decision_like: List[tuple] = []
        for c in configurations:
            if isinstance(c, dict):
                decision_like.append(("Configuration", c))
        for x in customizations:
            if isinstance(x, dict):
                decision_like.append(("Customization", x))
        for i in integrations:
            if isinstance(i, dict):
                decision_like.append(("Integration", i))
        for d in explicit_decisions:
            if isinstance(d, dict):
                decision_like.append(("Decision", d))

        trace_rows: List[List[str]] = []
        step_trace_rows: List[List[str]] = []
        for idx, (category, item) in enumerate(decision_like):
            refs = _requirement_refs(item)
            if refs:
                code = _decision_code(item) or "—"
                component = _clean(item.get('component') or item.get('name')) or "—"
                for rid in refs:
                    trace_rows.append([code, category, component, rid])
            prefs = _process_refs(item)
            if prefs:
                code = _decision_code(item) or "—"
                component = _clean(item.get('component') or item.get('name')) or "—"
                for sid in prefs:
                    step_trace_rows.append([code, category, component, sid])
        if trace_rows or step_trace_rows:
            doc.add_heading(f"{section_num}. Requirements Traceability", level=1)
            section_num += 1
            doc.add_paragraph(
                "The relationships below are sourced from the structured "
                "design data. They are not inferred."
            )
            if trace_rows:
                doc.add_heading("Requirement References", level=2)
                self._add_data_table(
                    doc,
                    ["Decision", "Decision Category", "Component", "Requirement ID"],
                    trace_rows,
                )
            if step_trace_rows:
                doc.add_heading("Process Step References", level=2)
                self._add_data_table(
                    doc,
                    ["Decision", "Decision Category", "Component", "Process Step ID"],
                    step_trace_rows,
                )

        if decision_like:
            doc.add_heading(f"{section_num}. Decision Register", level=1)
            section_num += 1
            doc.add_paragraph(
                "Summary of every design decision recorded in this document."
            )
            rows = []
            for category, item in decision_like:
                code = _decision_code(item) or "—"
                dtype = _or(
                    item.get('decision_type') or item.get('type'),
                    category,
                )
                component = _or(item.get('component') or item.get('name'))
                summary = _or(item.get('description') or item.get('summary'))
                stage = _or(item.get('stage'), "—")
                status = _or(item.get('status'), "—")
                classification = _or(item.get('classification'), "—")
                rows.append([
                    code, dtype, component, summary, stage, status, classification,
                ])
            self._add_data_table(
                doc,
                [
                    "Decision ID", "Decision Type", "Component",
                    "Summary", "Stage", "Status", "Classification",
                ],
                rows,
            )

        if explicit_decisions:
            doc.add_heading(f"{section_num}. Detailed Solution Decisions", level=1)
            section_num += 1
            any_rendered = False
            for d in explicit_decisions:
                if not isinstance(d, dict):
                    continue
                any_rendered = True
                doc.add_heading(_decision_heading(d, "Decision"), level=2)
                info = []
                for label, key in (
                    ("Decision Type", 'decision_type'),
                    ("Component", 'component'),
                    ("Stage", 'stage'),
                    ("Classification", 'classification'),
                    ("Status", 'status'),
                ):
                    v = _clean(d.get(key))
                    if v:
                        info.append((label, v))
                if info:
                    self._add_info_table(doc, info)
                desc = _clean(d.get('description'))
                if desc:
                    doc.add_heading("Description", level=3)
                    doc.add_paragraph(desc)
                rationale = _clean(d.get('rationale'))
                if rationale:
                    doc.add_heading("Rationale", level=3)
                    doc.add_paragraph(rationale)
                refs = _requirement_refs(d)
                if refs:
                    doc.add_heading("Requirement References", level=3)
                    self._add_bullet_list(doc, refs)
                prefs = _process_refs(d)
                if prefs:
                    doc.add_heading("Process Step References", level=3)
                    self._add_bullet_list(doc, prefs)
            if not any_rendered:
                doc.add_paragraph("No structured design decisions were supplied.")

        if configurations:
            doc.add_heading(f"{section_num}. Module Configuration", level=1)
            section_num += 1
            for c in configurations:
                if not isinstance(c, dict):
                    continue
                code = _decision_code(c)
                component = _clean(c.get('component')) or "Configuration"
                classification = _clean(c.get('classification'))
                if code and classification:
                    heading = f"{code} — {component} [{classification}]"
                elif code:
                    heading = f"{code} — {component}"
                elif classification:
                    heading = f"{component} [{classification}]"
                else:
                    heading = component
                doc.add_heading(heading, level=2)
                info = []
                if _clean(c.get('module')):
                    info.append(("Module", c['module']))
                if _clean(c.get('stage')):
                    info.append(("Stage", c['stage']))
                if _clean(c.get('status')):
                    info.append(("Status", c['status']))
                if _clean(c.get('rationale')):
                    info.append(("Rationale", c['rationale']))
                refs = _requirement_refs(c)
                if refs:
                    info.append(("Requirement References", ", ".join(refs)))
                prefs = _process_refs(c)
                if prefs:
                    info.append(("Process Step References", ", ".join(prefs)))
                if info:
                    self._add_info_table(doc, info)
                if _clean(c.get('description')):
                    doc.add_paragraph(c['description'])
                steps = c.get('steps') or []
                if steps:
                    doc.add_heading("Configuration Steps", level=3)
                    self._add_bullet_list(doc, steps)

        if integrations:
            doc.add_heading(f"{section_num}. Integration Design", level=1)
            section_num += 1
            for x in integrations:
                if not isinstance(x, dict):
                    continue
                code = _decision_code(x)
                name = _clean(x.get('name')) or "Integration"
                heading = f"{code} — {name}" if code else name
                doc.add_heading(heading, level=2)
                info = []
                for label, key in (
                    ("Type", 'type'),
                    ("Direction", 'direction'),
                    ("Source", 'source'),
                    ("Target", 'target'),
                    ("Trigger", 'trigger'),
                    ("Transport", 'transport'),
                    ("Frequency", 'frequency'),
                    ("Payload", 'payload_summary'),
                    ("Error Handling", 'error_handling'),
                    ("Idempotency Key", 'idempotency_key'),
                    ("Owner", 'owner'),
                    ("Stage", 'stage'),
                    ("Status", 'status'),
                ):
                    v = _clean(x.get(key))
                    if v:
                        info.append((label, v))
                refs = _requirement_refs(x)
                if refs:
                    info.append(("Requirement References", ", ".join(refs)))
                prefs = _process_refs(x)
                if prefs:
                    info.append(("Process Step References", ", ".join(prefs)))
                if info:
                    self._add_info_table(doc, info)
                if _clean(x.get('description')):
                    doc.add_paragraph(x['description'])

        if customizations:
            doc.add_heading(f"{section_num}. Customizations", level=1)
            section_num += 1
            doc.add_paragraph(
                "Customizations represent solution elements that extend the "
                "standard ERP product."
            )
            for c in customizations:
                if not isinstance(c, dict):
                    continue
                code = _decision_code(c)
                component = _clean(c.get('component')) or "Customization"
                ctype = _clean(c.get('type'))
                if code and ctype:
                    heading = f"{code} — {component} [{ctype}]"
                elif code:
                    heading = f"{code} — {component}"
                elif ctype:
                    heading = f"{component} [{ctype}]"
                else:
                    heading = component
                doc.add_heading(heading, level=2)
                info = []
                for label, key in (
                    ("Component", 'component'),
                    ("Type", 'type'),
                    ("Classification", 'classification'),
                    ("Complexity", 'complexity'),
                    ("Status", 'status'),
                ):
                    v = _clean(c.get(key))
                    if v:
                        info.append((label, v))
                refs = _requirement_refs(c)
                if refs:
                    info.append(("Requirement References", ", ".join(refs)))
                prefs = _process_refs(c)
                if prefs:
                    info.append(("Process Step References", ", ".join(prefs)))
                if info:
                    self._add_info_table(doc, info)
                if _clean(c.get('description')):
                    doc.add_heading("Description", level=3)
                    doc.add_paragraph(c['description'])
                rationale = _clean(c.get('justification') or c.get('rationale'))
                if rationale:
                    doc.add_heading("Rationale", level=3)
                    doc.add_paragraph(rationale)
                alt_list = _as_list(c.get('alternatives_considered'))
                if alt_list:
                    doc.add_heading("Alternatives Considered", level=3)
                    self._add_bullet_list(doc, alt_list)
                lifecycle = _clean(c.get('lifecycle_impact'))
                if lifecycle:
                    doc.add_heading("Lifecycle Impact", level=3)
                    doc.add_paragraph(lifecycle)

        md_items = des.get('master_data_items')
        md_flat = des.get('master_data') or {}
        if (isinstance(md_items, list) and md_items) or (
            isinstance(md_flat, dict) and md_flat
        ):
            doc.add_heading(f"{section_num}. Master Data", level=1)
            section_num += 1
            if isinstance(md_items, list) and md_items:
                rows = []
                for m in md_items:
                    if not isinstance(m, dict):
                        continue
                    rows.append([
                        _or(m.get('data_type')),
                        _or(m.get('status'), "—"),
                        _or(m.get('owner'), "—"),
                        _or(m.get('details'), "—"),
                    ])
                if rows:
                    self._add_data_table(
                        doc, ["Data Type", "Status", "Owner", "Details"], rows,
                    )
            else:
                rows = [[_or(k), _or(v)] for k, v in md_flat.items()]
                if rows:
                    self._add_data_table(doc, ["Data Type", "Details"], rows)

        security = des.get('security') or {}
        if isinstance(security, dict) and any(security.values()):
            doc.add_heading(f"{section_num}. Security and Authorization", level=1)
            section_num += 1
            if _clean(security.get('overview')):
                doc.add_paragraph(security['overview'])
            if _clean(security.get('authorization_model')):
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

        migration = des.get('migration') or {}
        if isinstance(migration, dict) and any(migration.values()):
            doc.add_heading(f"{section_num}. Migration Strategy", level=1)
            section_num += 1
            if _clean(migration.get('approach')):
                sub = doc.add_paragraph()
                r = sub.add_run(f"Approach: {migration['approach']}")
                r.bold = True
            if _clean(migration.get('strategy')):
                doc.add_heading("Summary", level=2)
                doc.add_paragraph(migration['strategy'])
            if _clean(migration.get('cutover_window')):
                doc.add_heading("Cutover Window", level=2)
                doc.add_paragraph(migration['cutover_window'])
            if migration.get('data_scope'):
                doc.add_heading("Data Scope", level=2)
                self._add_bullet_list(doc, migration['data_scope'])
            if _clean(migration.get('reconciliation_approach')):
                doc.add_heading("Reconciliation", level=2)
                doc.add_paragraph(migration['reconciliation_approach'])
            if _clean(migration.get('rollback_approach')):
                doc.add_heading("Rollback Approach", level=2)
                doc.add_paragraph(migration['rollback_approach'])

        ts_items = des.get('technical_specs_items')
        ts_flat = des.get('technical_specs') or {}
        if (isinstance(ts_items, list) and ts_items) or (
            isinstance(ts_flat, dict) and ts_flat
        ):
            doc.add_heading(f"{section_num}. Technical Specifications", level=1)
            section_num += 1
            if isinstance(ts_items, list) and ts_items:
                rows = []
                for t in ts_items:
                    if not isinstance(t, dict):
                        continue
                    rows.append([
                        _or(t.get('category')),
                        _or(t.get('name')),
                        _or(t.get('value')),
                    ])
                if rows:
                    self._add_data_table(doc, ["Category", "Name", "Value"], rows)
            else:
                rows = [[_or(k), _or(v)] for k, v in ts_flat.items()]
                if rows:
                    self._add_data_table(doc, ["Specification", "Value"], rows)

        impacts = des.get('business_impacts') or des.get('impacts') or []
        if impacts:
            doc.add_heading(f"{section_num}. Business Impact", level=1)
            section_num += 1
            has_struct = any(isinstance(x, dict) for x in impacts)
            if has_struct:
                rows = []
                for x in impacts:
                    if isinstance(x, dict):
                        rows.append([
                            _or(x.get('business_area') or x.get('area'), "—"),
                            _or(x.get('impact'), "—"),
                            _or(x.get('operational_change'), "—"),
                            _or(x.get('user_impact'), "—"),
                            _or(x.get('dependency'), "—"),
                        ])
                    else:
                        rows.append([str(x), "—", "—", "—", "—"])
                if rows:
                    self._add_data_table(
                        doc,
                        [
                            "Affected Business Area", "Impact",
                            "Operational Change", "User Impact", "Dependency",
                        ],
                        rows,
                    )
            else:
                self._add_bullet_list(doc, impacts)

        assumptions = des.get('assumptions') or []
        if assumptions:
            doc.add_heading(f"{section_num}. Assumptions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Assumptions recorded during design. An assumption is not a "
                "confirmed design decision."
            )
            self._add_bullet_list(doc, assumptions)

        open_qs = des.get('open_questions') or []
        if open_qs:
            doc.add_heading(f"{section_num}. Open Questions", level=1)
            section_num += 1
            doc.add_paragraph(
                "Open design questions remain unresolved. Blocking items "
                "must be resolved before the affected decision can be "
                "confirmed."
            )
            rows = []
            for q in open_qs:
                if isinstance(q, dict):
                    rows.append([
                        _or(q.get('question'), "—"),
                        _or(q.get('context') or q.get('topic'), ""),
                        _or(q.get('owner'), ""),
                        "Yes" if q.get('blocking') else "No",
                    ])
                else:
                    rows.append([str(q), "", "", "No"])
            self._add_data_table(
                doc, ["Question", "Context", "Owner", "Blocking"], rows,
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
    # Consolidated project status report
    # ------------------------------------------------------------------

    def generate_project_report(self, session_id: str) -> str:
        """Generate the ERP Implementation Project Status Report.

        A governance-oriented, point-in-time summary of the project's
        current state. All content is sourced from project_intelligence
        and SessionRecord. Nothing is fabricated: no milestones, dates,
        owners, risks, percentages, RAG statuses, or completion claims
        that the source data does not directly support. Where the source
        lacks a value, the section is either omitted or rendered with an
        explicit placeholder.
        """
        from src.memory import session_service
        from src.services import project_intelligence

        session = session_service.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        requirements = project_intelligence.get_requirements(session_id) or []
        process_steps = project_intelligence.get_process_steps(session_id) or []
        solution_decisions = project_intelligence.get_solution_decisions(session_id) or []
        test_cases = project_intelligence.get_test_cases(session_id) or []
        training_steps = project_intelligence.get_training_steps(session_id) or []
        open_issues = project_intelligence.get_issues(session_id, status="open") or []
        health = project_intelligence.get_project_health(session_id) or {}
        gaps = project_intelligence.get_coverage_gaps(session_id) or {}

        def _clean(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        def _or(value: Any, placeholder: str = "Not provided") -> str:
            s = _clean(value)
            return s if s else placeholder

        def _phase_label(phase: Any) -> str:
            mapping = {
                'requirements_gathering': 'Requirements',
                'process_mapping': 'Process Mapping',
                'solution_design': 'Solution Design',
                'qa_testing': 'QA Testing',
                'uat_testing': 'UAT',
                'training': 'Training',
                'completed': 'Completed',
            }
            raw = _clean(phase)
            if not raw:
                return "Not provided"
            key = raw.lower()
            if key in mapping:
                return mapping[key]
            return raw.replace('_', ' ').title()

        def _counter(items: List[Any], key: str) -> Dict[str, int]:
            out: Dict[str, int] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                k = _clean(it.get(key)) or "Unspecified"
                out[k] = out.get(k, 0) + 1
            return out

        qa_cases = [
            tc for tc in test_cases
            if isinstance(tc, dict) and _clean(tc.get('test_type')) == 'QA'
        ]
        uat_cases = [
            tc for tc in test_cases
            if isinstance(tc, dict) and _clean(tc.get('test_type')) != 'QA'
        ]

        req_total = len(requirements)
        proc_total = len(process_steps)
        design_total = len(solution_decisions)
        training_total = len(training_steps)

        unique_processes = set()
        for s in process_steps:
            if isinstance(s, dict):
                pn = _clean(s.get('process_name'))
                if pn:
                    unique_processes.add(pn)

        no_req_steps = 0
        for s in process_steps:
            if not isinstance(s, dict):
                continue
            rid = s.get('requirement_id')
            if rid in (None, "", []):
                no_req_steps += 1

        qa_retest = sum(
            1 for tc in qa_cases
            if isinstance(tc, dict) and tc.get('needs_retest')
        )
        uat_retest = sum(
            1 for tc in uat_cases
            if isinstance(tc, dict) and tc.get('needs_retest')
        )
        training_missing_verification = sum(
            1 for t in training_steps
            if isinstance(t, dict) and not _clean(t.get('verification'))
        )
        training_missing_prereqs = sum(
            1 for t in training_steps
            if isinstance(t, dict) and not t.get('prerequisites')
        )

        pending_decisions = [
            d for d in solution_decisions
            if isinstance(d, dict) and _clean(d.get('status')).lower() == 'proposed'
        ]

        uncovered = gaps.get('uncovered_requirements') or []
        untested = gaps.get('untested_requirements') or []

        doc = self._new_document(
            "ERP Implementation Project Status Report",
            session.project_name,
        )

        section_num = 1

        # ---------- 1. Document Information ----------
        doc.add_heading(f"{section_num}. Document Information", level=1)
        section_num += 1
        self._add_info_table(doc, [
            ("Project", session.project_name),
            ("ERP System", _or(session.erp_system)),
            ("Module / Functional Area", _or(session.module)),
            ("Current Phase", _phase_label(session.current_phase)),
            ("Report Date", _utcnow().strftime('%Y-%m-%d')),
            ("Document Type", "ERP Implementation Project Status Report"),
            ("Document Status", "Draft for Review"),
            ("Version", "1.0"),
            ("Prepared Date", _utcnow().strftime('%Y-%m-%d')),
        ])

        # ---------- 2. Executive Summary ----------
        doc.add_heading(f"{section_num}. Executive Summary", level=1)
        section_num += 1
        exec_bits: List[str] = []
        if _clean(session.current_phase):
            exec_bits.append(
                f"The project is currently in the "
                f"{_phase_label(session.current_phase)} phase."
            )
        if req_total:
            exec_bits.append(f"{req_total} requirement(s) have been captured.")
        coverage_pct = health.get('requirements_coverage_pct')
        if coverage_pct is not None:
            exec_bits.append(f"Downstream coverage is {coverage_pct}%.")
        if open_issues:
            exec_bits.append(
                f"{len(open_issues)} open issue(s) require attention."
            )
        if not exec_bits:
            exec_bits.append(
                "Project status metrics are not yet available for this "
                "report."
            )
        doc.add_paragraph(" ".join(exec_bits))

        coverage_display = (
            f"{coverage_pct}%" if coverage_pct is not None else "Not provided"
        )
        self._add_data_table(doc, ["Indicator", "Value"], [
            ["Requirements captured", req_total],
            ["Downstream coverage", coverage_display],
            ["Open issues", len(open_issues)],
            ["Process steps recorded", proc_total],
            ["Solution decisions recorded", design_total],
            ["QA test cases", len(qa_cases)],
            ["UAT test cases", len(uat_cases)],
            ["Training steps", training_total],
        ])

        # ---------- 3. Overall Project Status ----------
        doc.add_heading(f"{section_num}. Overall Project Status", level=1)
        section_num += 1
        status_rows: List[List[Any]] = []
        for label, key in (
            ("Requirements Total", "requirements_total"),
            ("Requirements Coverage (%)", "requirements_coverage_pct"),
            ("Open Issues Total", "open_issues_total"),
            ("Uncovered Requirements", "uncovered_requirements_total"),
            ("Untested Requirements", "untested_requirements_total"),
        ):
            v = health.get(key) if isinstance(health, dict) else None
            if v is not None:
                status_rows.append([label, v])
        if status_rows:
            self._add_data_table(doc, ["Metric", "Value"], status_rows)
        else:
            doc.add_paragraph(
                "Project health summary is not available for this report."
            )

        # ---------- 4. Workstream Status ----------
        doc.add_heading(f"{section_num}. Workstream Status", level=1)
        section_num += 1
        doc.add_paragraph(
            "The table below shows the record count per workstream and "
            "whether that workstream has open attention items. Counts are "
            "record counts from the underlying data; they do not by "
            "themselves indicate completion."
        )
        proc_label = f"{len(unique_processes)} process(es), {proc_total} step(s)"
        workstream_rows = [
            ["Requirements", req_total, "Yes" if (uncovered or untested) else "No"],
            ["Process Mapping", proc_label, "Yes" if no_req_steps else "No"],
            ["Solution Design", design_total, "Yes" if pending_decisions else "No"],
            ["QA Testing", len(qa_cases), "Yes" if qa_retest else "No"],
            ["UAT Testing", len(uat_cases), "Yes" if uat_retest else "No"],
            ["Training", training_total,
             "Yes" if (training_missing_verification or training_missing_prereqs) else "No"],
        ]
        self._add_data_table(
            doc,
            ["Workstream", "Record Count", "Attention Required"],
            workstream_rows,
        )

        # ---------- 5. Requirements Status ----------
        if requirements:
            doc.add_heading(f"{section_num}. Requirements Status", level=1)
            section_num += 1
            self._add_data_table(doc, ["Metric", "Value"], [
                ["Total requirements", req_total],
            ])
            by_status = _counter(requirements, 'status')
            if by_status:
                doc.add_heading("By Status", level=2)
                self._add_data_table(
                    doc, ["Status", "Count"],
                    [[k, v] for k, v in by_status.items()],
                )
            by_priority = _counter(requirements, 'priority')
            if by_priority:
                doc.add_heading("By Priority", level=2)
                self._add_data_table(
                    doc, ["Priority", "Count"],
                    [[k, v] for k, v in by_priority.items()],
                )
            by_category = _counter(requirements, 'category')
            if by_category:
                doc.add_heading("By Category", level=2)
                self._add_data_table(
                    doc, ["Category", "Count"],
                    [[k, v] for k, v in by_category.items()],
                )

        # ---------- 6. Process Mapping Status ----------
        if process_steps:
            doc.add_heading(f"{section_num}. Process Mapping Status", level=1)
            section_num += 1
            proc_rows = [
                ["Processes represented", len(unique_processes)],
                ["Process steps recorded", proc_total],
                ["Steps without requirement linkage", no_req_steps],
            ]
            self._add_data_table(doc, ["Metric", "Value"], proc_rows)
            if unique_processes:
                doc.add_heading("Processes Represented", level=2)
                self._add_bullet_list(doc, sorted(unique_processes))

        # ---------- 7. Solution Design Status ----------
        if solution_decisions:
            doc.add_heading(f"{section_num}. Solution Design Status", level=1)
            section_num += 1
            self._add_data_table(doc, ["Metric", "Value"], [
                ["Total solution decisions", design_total],
                ["Decisions currently proposed", len(pending_decisions)],
            ])
            by_type = _counter(solution_decisions, 'decision_type')
            if by_type:
                doc.add_heading("By Decision Type", level=2)
                self._add_data_table(
                    doc, ["Decision Type", "Count"],
                    [[k, v] for k, v in by_type.items()],
                )
            by_status = _counter(solution_decisions, 'status')
            if by_status:
                doc.add_heading("By Status", level=2)
                self._add_data_table(
                    doc, ["Status", "Count"],
                    [[k, v] for k, v in by_status.items()],
                )

        # ---------- 8. Testing Status ----------
        if test_cases:
            doc.add_heading(f"{section_num}. Testing Status", level=1)
            section_num += 1
            doc.add_heading("QA Testing", level=2)
            self._add_data_table(doc, ["Metric", "Value"], [
                ["QA test cases", len(qa_cases)],
                ["QA test cases requiring retest", qa_retest],
            ])
            doc.add_heading("UAT Testing", level=2)
            self._add_data_table(doc, ["Metric", "Value"], [
                ["UAT test cases", len(uat_cases)],
                ["UAT test cases requiring retest", uat_retest],
            ])

        # ---------- 9. Training Status ----------
        if training_steps:
            doc.add_heading(f"{section_num}. Training Status", level=1)
            section_num += 1
            rows = [
                ["Training steps recorded", training_total],
                ["Steps with missing verification", training_missing_verification],
                ["Steps with missing prerequisites", training_missing_prereqs],
            ]
            self._add_data_table(doc, ["Metric", "Value"], rows)
            by_role = _counter(training_steps, 'role')
            if by_role:
                doc.add_heading("By Role", level=2)
                self._add_data_table(
                    doc, ["Role", "Count"],
                    [[k, v] for k, v in by_role.items()],
                )

        # ---------- 10. Traceability and Coverage ----------
        if uncovered or untested or no_req_steps:
            doc.add_heading(f"{section_num}. Traceability and Coverage", level=1)
            section_num += 1
            doc.add_paragraph(
                "The items below are missing a downstream link in the "
                "recorded project data. Only stored relationships are "
                "reported; no coverage is inferred."
            )
            if uncovered:
                doc.add_heading("Requirements without downstream coverage", level=2)
                rows = []
                for r in uncovered:
                    if isinstance(r, dict):
                        rows.append([
                            _or(r.get('id') or r.get('external_code'), "—"),
                            _or(r.get('description'), "—"),
                        ])
                if rows:
                    self._add_data_table(
                        doc,
                        ["Requirement ID", "Description"],
                        rows,
                    )
            if untested:
                doc.add_heading("Requirements without test coverage", level=2)
                rows = []
                for r in untested:
                    if isinstance(r, dict):
                        rows.append([
                            _or(r.get('id') or r.get('external_code'), "—"),
                            _or(r.get('description'), "—"),
                        ])
                if rows:
                    self._add_data_table(
                        doc,
                        ["Requirement ID", "Description"],
                        rows,
                    )
            if no_req_steps:
                doc.add_paragraph(
                    f"{no_req_steps} process step(s) do not have a "
                    f"requirement linkage recorded in the source data."
                )

        # ---------- 11. Open Issues and Attention Items ----------
        if open_issues:
            doc.add_heading(f"{section_num}. Open Issues and Attention Items", level=1)
            section_num += 1
            rows = []
            for i in open_issues:
                if not isinstance(i, dict):
                    continue
                rows.append([
                    _or(i.get('id') or i.get('issue_id'), "—"),
                    _or(i.get('issue_type'), "—"),
                    _or(i.get('severity'), "—"),
                    _or(i.get('description'), "—"),
                    _or(i.get('status'), "—"),
                ])
            if rows:
                self._add_data_table(
                    doc,
                    ["Issue ID", "Type", "Severity", "Description", "Status"],
                    rows,
                )

        # ---------- 12. Decisions Required ----------
        if pending_decisions:
            doc.add_heading(f"{section_num}. Decisions Required", level=1)
            section_num += 1
            doc.add_paragraph(
                "The design decisions below are recorded with a status of "
                "'proposed'. They require governance attention before they "
                "are confirmed."
            )
            rows = []
            for d in pending_decisions:
                if not isinstance(d, dict):
                    continue
                rows.append([
                    _or(d.get('external_code') or d.get('id'), "—"),
                    _or(d.get('decision_type') or d.get('type'), "—"),
                    _or(d.get('component'), "—"),
                    _or(d.get('status'), "—"),
                ])
            if rows:
                self._add_data_table(
                    doc,
                    ["Decision ID", "Type", "Component", "Status"],
                    rows,
                )

        # ---------- 13. Review and Approval ----------
        doc.add_heading(f"{section_num}. Review and Approval", level=1)
        section_num += 1
        doc.add_paragraph(
            "This report is a draft for review. Fields marked 'To be "
            "completed' remain outstanding. Completion of this review "
            "does not itself constitute approval of the project state."
        )
        self._add_data_table(
            doc,
            ["Reviewer", "Role", "Review Status", "Review Date", "Comments"],
            [
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
                ["", "", "To be completed", "", ""],
            ],
        )

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