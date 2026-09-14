from io import BytesIO
import pytest
from docx import Document as DocxDocument
from reportlab.pdfgen import canvas

from src.tools.document_extractor import extract_text, UnsupportedFileType, MAX_EXTRACTED_CHARS


def _make_docx_bytes(paragraphs):
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(lines):
    buf = BytesIO()
    c = canvas.Canvas(buf)
    y = 750
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


class TestUnsupportedTypes:
    def test_raises_for_unsupported_extension(self):
        with pytest.raises(UnsupportedFileType):
            extract_text("malware.exe", b"whatever")

    def test_raises_for_no_extension(self):
        with pytest.raises(UnsupportedFileType):
            extract_text("noextension", b"whatever")


class TestTxtAndMd:
    def test_extracts_plain_txt(self):
        result = extract_text("notes.txt", b"Some plain notes about the FI module.")
        assert result == "Some plain notes about the FI module."

    def test_extracts_markdown_as_plain_text(self):
        result = extract_text("notes.md", b"# Heading\n\nSome content.")
        assert "Heading" in result and "Some content." in result

    def test_handles_invalid_utf8_without_crashing(self):
        result = extract_text("notes.txt", b"\xff\xfe not valid utf8")
        assert isinstance(result, str)  # replaced, not raised


class TestDocx:
    def test_extracts_paragraph_text(self):
        content = _make_docx_bytes(["First paragraph about requirements.", "Second paragraph about scope."])
        result = extract_text("spec.docx", content)
        assert "First paragraph about requirements." in result
        assert "Second paragraph about scope." in result

    def test_corrupt_docx_returns_empty_string_not_an_exception(self):
        result = extract_text("broken.docx", b"this is not a real docx file")
        assert result == ""


class TestPdf:
    def test_extracts_text_from_a_real_pdf(self):
        content = _make_pdf_bytes(["Purchase order approval workflow.", "Requires manager sign-off above $5000."])
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


class TestLengthCap:
    def test_extracted_text_is_capped_at_max_length(self):
        huge = "word " * 10_000  # far more than MAX_EXTRACTED_CHARS
        result = extract_text("huge.txt", huge.encode())
        assert len(result) == MAX_EXTRACTED_CHARS
