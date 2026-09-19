"""
Tests for src/tools/document_extractor.extract_text.

The extractor is the on-ramp for consultant-uploaded documents: it
turns the raw bytes into text that gets stored as project memory and
fed into agent context. Two families of behavior matter:

  Success cases
    - Plain text formats (.txt, .md) pass through unchanged.
    - .docx extracts paragraph text AND table cell text.
    - .pdf extracts text from text-layer PDFs.
    - Long content is capped at MAX_EXTRACTED_CHARS.

  Failure cases
    - Unsupported extensions raise UnsupportedFileType.
    - Corrupt files return "" rather than raising — a malformed
      upload must not take down the endpoint.
    - Invalid UTF-8 is handled with replacement characters, not a
      UnicodeDecodeError.

Coverage notes:
  - The DOCX table test is the highest-value addition: python-docx's
    Document.paragraphs does not include table cell content. If the
    extractor only reads paragraphs, a table-only requirements
    document extracts to "" — a silent content-loss scenario for
    exactly the kind of document a consultant is likely to upload.
  - Extension matching is tested case-insensitively, since Windows and
    macOS filenames are commonly mixed case.
  - Filenames with path separators are treated as bare names, not
    resolved paths — a defensive test for a potential traversal
    surface.
  - The length cap is tested at three points: well below, exactly at,
    and well above MAX_EXTRACTED_CHARS. An off-by-one regression at
    either boundary would fail.

Test helpers:
  _make_docx_bytes and _make_pdf_bytes construct real in-memory
  documents so the tests exercise the actual parser code paths, not
  mocks. Both are cheap (a few milliseconds each).
"""
from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document as DocxDocument
from reportlab.pdfgen import canvas

from src.tools.document_extractor import (
    MAX_EXTRACTED_CHARS,
    SUPPORTED_EXTENSIONS,
    UnsupportedFileType,
    extract_text,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
def _make_docx_bytes(paragraphs=None, tables=None) -> bytes:
    """Build a real .docx in memory. Either argument may be omitted;
    when both are given, paragraphs come first, then tables."""
    doc = DocxDocument()
    for p in (paragraphs or []):
        doc.add_paragraph(p)
    for table_data in (tables or []):
        # table_data is a list of rows, each row a list of cell values.
        if not table_data:
            continue
        table = doc.add_table(rows=len(table_data), cols=len(table_data[0]))
        for r, row in enumerate(table_data):
            for c, value in enumerate(row):
                table.rows[r].cells[c].text = value
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(lines) -> bytes:
    """Build a real text-layer PDF in memory."""
    buf = BytesIO()
    c = canvas.Canvas(buf)
    y = 750
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


# ===========================================================================
# Unsupported types
# ===========================================================================
class TestUnsupportedTypes:
    def test_raises_for_unsupported_extension(self):
        with pytest.raises(UnsupportedFileType):
            extract_text("malware.exe", b"whatever")

    def test_raises_for_no_extension(self):
        with pytest.raises(UnsupportedFileType):
            extract_text("noextension", b"whatever")

    @pytest.mark.parametrize("filename", [
        "archive.zip",
        "image.png",
        "video.mp4",
        "script.sh",
        "executable.bin",
    ])
    def test_raises_for_assorted_binary_extensions(self, filename):
        """A range of plausible upload mistakes must all raise rather
        than reaching a parser that would misbehave on binary input."""
        with pytest.raises(UnsupportedFileType):
            extract_text(filename, b"binary junk")

    def test_raises_for_legacy_doc_extension(self):
        """Legacy .doc (pre-2007 Word) is not readable by python-docx.
        The extractor must reject it explicitly rather than returning
        empty text for a document the user believes was processed.

        If the implementation is later extended to support .doc (via a
        converter), this test should be updated rather than removed —
        the behavior must remain deliberate."""
        with pytest.raises(UnsupportedFileType):
            extract_text("old_format.doc", b"\xd0\xcf\x11\xe0 legacy binary")


# ===========================================================================
# Supported extensions surface
# ===========================================================================
class TestSupportedExtensions:
    def test_common_text_extensions_are_supported(self):
        """The set is imported and asserted on so that a change to it
        is a conscious edit, not a silent regression."""
        for ext in (".txt", ".md"):
            assert ext in SUPPORTED_EXTENSIONS, (
                f"{ext!r} should be in SUPPORTED_EXTENSIONS — a plain "
                "text file is the simplest thing a user can upload"
            )

    def test_rich_document_extensions_are_supported(self):
        for ext in (".docx", ".pdf"):
            assert ext in SUPPORTED_EXTENSIONS


# ===========================================================================
# TXT and MD
# ===========================================================================
class TestTxtAndMd:
    def test_extracts_plain_txt(self):
        result = extract_text("notes.txt", b"Some plain notes about the FI module.")
        assert result == "Some plain notes about the FI module."

    def test_extracts_markdown_as_plain_text(self):
        result = extract_text("notes.md", b"# Heading\n\nSome content.")
        assert "Heading" in result and "Some content." in result

    def test_extension_matching_is_case_insensitive(self):
        """'NOTES.TXT' and 'NOTES.Txt' are the same file type. Windows
        and macOS produce mixed-case extensions routinely; the check
        must not depend on the case of the extension."""
        for filename in ("NOTES.TXT", "Notes.Txt", "NOTES.MD"):
            result = extract_text(filename, b"case insensitive content")
            assert "case insensitive content" in result, (
                f"case-insensitive extension matching failed for {filename}"
            )

    def test_handles_invalid_utf8_with_replacement(self):
        """Invalid bytes must be replaced with U+FFFD and the ASCII
        content around them preserved — not silently dropped."""
        result = extract_text("notes.txt", b"valid prefix \xff\xfe valid suffix")
        # Some form of the valid content is present.
        assert "valid prefix" in result
        assert "valid suffix" in result
        # The invalid bytes were replaced, not raised.
        assert "\ufffd" in result

    def test_empty_file_returns_empty_string(self):
        """A zero-byte .txt upload is a plausible user mistake and
        should produce empty text, not an exception."""
        assert extract_text("empty.txt", b"") == ""

    def test_whitespace_only_content_is_preserved_or_empty(self):
        """A file of only newlines/spaces has no information. Whether
        the extractor preserves it or strips to "" is a design choice;
        either is fine, but it must not raise or return None."""
        result = extract_text("blank.txt", b"\n\n   \n\t\n")
        assert isinstance(result, str)
        assert result.strip() == ""


# ===========================================================================
# DOCX
# ===========================================================================
class TestDocx:
    def test_extracts_paragraph_text(self):
        content = _make_docx_bytes([
            "First paragraph about requirements.",
            "Second paragraph about scope.",
        ])
        result = extract_text("spec.docx", content)
        assert "First paragraph about requirements." in result
        assert "Second paragraph about scope." in result

    def test_extracts_table_cell_text(self):
        """This is the highest-value DOCX test. python-docx's
        Document.paragraphs does NOT include table cell content — a
        reader that only walks paragraphs will silently extract
        nothing from a table-only document.

        ERP requirement documents, RACI matrices, and integration
        lists are frequently table-shaped, so failing to read tables
        means failing to read the most important content in the most
        likely documents."""
        content = _make_docx_bytes(tables=[
            [
                ["Requirement ID", "Description", "Priority"],
                ["REQ-001", "Create purchase orders", "High"],
                ["REQ-002", "Three-way match", "High"],
            ],
        ])
        result = extract_text("requirements_matrix.docx", content)
        assert "REQ-001" in result, (
            "table cell content was not extracted — the DOCX reader "
            "must walk tables in addition to top-level paragraphs"
        )
        assert "Three-way match" in result

    def test_extracts_paragraphs_and_tables_together(self):
        """A mixed document (paragraphs introducing a table) is the
        common shape. Both must be captured."""
        content = _make_docx_bytes(
            paragraphs=["The following is the current approval matrix:"],
            tables=[
                [["Role", "Limit"], ["Manager", "$5,000"], ["Director", "$50,000"]],
            ],
        )
        result = extract_text("approvals.docx", content)
        assert "approval matrix" in result
        assert "Manager" in result
        assert "$50,000" in result

    def test_corrupt_docx_returns_empty_string_not_an_exception(self):
        result = extract_text("broken.docx", b"this is not a real docx file")
        assert result == ""


# ===========================================================================
# PDF
# ===========================================================================
class TestPdf:
    def test_extracts_text_from_a_real_pdf(self):
        content = _make_pdf_bytes([
            "Purchase order approval workflow.",
            "Requires manager sign-off above $5000.",
        ])
        result = extract_text("workflow.pdf", content)
        assert "Purchase order approval workflow." in result
        assert "manager sign-off" in result

    def test_blank_pdf_with_no_text_returns_empty_string(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = BytesIO()
        writer.write(buf)
        result = extract_text("scanned.pdf", buf.getvalue())
        assert result == ""

    def test_corrupt_pdf_returns_empty_string_not_an_exception(self):
        result = extract_text("broken.pdf", b"%PDF-1.4 not actually valid content")
        assert result == ""

    def test_empty_pdf_bytes_return_empty_string(self):
        """A .pdf file with zero bytes is a plausible upload artifact
        (a failed download). It must not raise."""
        assert extract_text("empty.pdf", b"") == ""


# ===========================================================================
# Length cap
# ===========================================================================
class TestLengthCap:
    def test_extracted_text_is_capped_at_max_length(self):
        huge = "word " * 10_000  # 50,000 chars, well above the cap
        result = extract_text("huge.txt", huge.encode())
        assert len(result) == MAX_EXTRACTED_CHARS, (
            f"the cap should truncate to exactly {MAX_EXTRACTED_CHARS} "
            f"chars; got {len(result)}"
        )

    def test_short_content_is_not_truncated(self):
        """The counterpart to the previous test: content well below the
        cap must pass through unchanged. A regression that truncated
        unconditionally would still pass the huge-input test but
        silently corrupt every small document."""
        short = "This is a short note about the FI module."
        result = extract_text("short.txt", short.encode())
        assert result == short, (
            "short content should not be truncated — the cap must only "
            "apply when the input exceeds it"
        )

    def test_content_exactly_at_the_cap_is_preserved(self):
        """Boundary case: content of exactly MAX_EXTRACTED_CHARS must
        be preserved in full. An off-by-one error at `>` vs. `>=`
        would truncate one character too many."""
        exact = "a" * MAX_EXTRACTED_CHARS
        result = extract_text("exact.txt", exact.encode())
        assert len(result) == MAX_EXTRACTED_CHARS
        assert result == exact

    def test_content_one_char_over_the_cap_is_capped(self):
        """Boundary case: content of MAX_EXTRACTED_CHARS + 1 must be
        capped at MAX_EXTRACTED_CHARS. Symmetric to the previous test."""
        over = "b" * (MAX_EXTRACTED_CHARS + 1)
        result = extract_text("over.txt", over.encode())
        assert len(result) == MAX_EXTRACTED_CHARS


# ===========================================================================
# Filename handling
# ===========================================================================
class TestFilenameHandling:
    def test_filename_with_path_separator_treated_as_bare_name(self):
        """A filename with a directory separator must be treated as a
        bare filename for extension purposes — the extractor never
        resolves or opens a path, but the check must be robust against
        a caller that passes one."""
        result = extract_text("subdir/notes.txt", b"content from subdir")
        assert result == "content from subdir"

    def test_filename_with_traversal_sequence_treated_as_bare_name(self):
        """Defensive: a filename like '../../etc/passwd.txt' must not
        cause the extractor to read outside the upload. The extension
        is .txt, so it parses as plain text — the traversal is a
        non-issue for content, but the test documents that the reader
        does not interpret the filename as a path."""
        result = extract_text("../../etc/passwd.txt", b"not the real passwd file")
        assert result == "not the real passwd file"

    def test_filename_with_only_a_dot_raises(self):
        """'file.' has no meaningful extension — it should be rejected
        the same way 'noextension' is."""
        with pytest.raises(UnsupportedFileType):
            extract_text("file.", b"content")

    def test_filename_with_multiple_dots_uses_final_extension(self):
        """'report.final.docx' has extension '.docx', not '.final'.
        Path.suffix returns the last component, which is what we
        want — but the behavior should be pinned."""
        content = _make_docx_bytes(["content from a multi-dot filename"])
        result = extract_text("report.final.docx", content)
        assert "content from a multi-dot filename" in result


# ===========================================================================
# Unicode and encoding
# ===========================================================================
class TestEncoding:
    def test_utf8_non_ascii_is_preserved(self):
        """A UTF-8 file with accented characters, currency symbols, or
        non-Latin scripts should round-trip cleanly."""
        content = "Café — €5000 — 日本語".encode("utf-8")
        result = extract_text("unicode.txt", content)
        assert "Café" in result
        assert "€5000" in result
        assert "日本語" in result

    def test_latin1_encoded_file_does_not_crash(self):
        """A file saved in Latin-1 (a common artifact from older
        systems) is not valid UTF-8 for the accented bytes. The
        extractor must not raise — it should either decode with
        replacement or fall back to a lenient codec."""
        # 'é' in Latin-1 is 0xE9, which is not a valid standalone UTF-8 byte.
        latin1_bytes = "Caf\xe9 notes".encode("latin-1")
        result = extract_text("latin1.txt", latin1_bytes)
        assert isinstance(result, str)
        # The ASCII portions survive regardless of how the 0xE9 byte is handled.
        assert "notes" in result