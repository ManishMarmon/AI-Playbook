import io
import zipfile
from datetime import datetime

import pytest

from docx_redline import parse_docx_redline

_DOC_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:body>'
)
_DOC_FOOTER = '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>'


def _make_docx(body_xml: str) -> bytes:
    # docx_redline.py only ever reads word/document.xml by name — the rest
    # of a real OPC package (Content_Types, rels, ...) is irrelevant to it,
    # so tests only need this one part.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", (_DOC_HEADER + body_xml + _DOC_FOOTER).encode("utf-8"))
    return buf.getvalue()


def test_no_tracked_changes():
    body = "<w:p><w:r><w:t>Plain paragraph, no edits.</w:t></w:r></w:p>"
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert result["has_tracked_changes"] is False
    assert result["edit_count"] == 0
    assert "Plain paragraph, no edits." in result["base_text"]
    assert "Plain paragraph, no edits." in result["proposed_text"]


def test_insertion_and_deletion_with_authors_and_dates():
    body = (
        "<w:p>"
        '<w:r><w:t xml:space="preserve">The Effective Date is </w:t></w:r>'
        '<w:ins w:id="1" w:author="Jane Doe" w:date="2024-01-15T10:00:00Z">'
        "<w:r><w:t>January 1, 2024</w:t></w:r>"
        "</w:ins>"
        '<w:r><w:t xml:space="preserve">. </w:t></w:r>'
        "</w:p>"
        "<w:p>"
        '<w:del w:id="2" w:author="John Smith" w:date="2024-01-16T09:30:00Z">'
        "<w:r><w:delText>This clause is void if not executed within 30 days.</w:delText></w:r>"
        "</w:del>"
        "</w:p>"
        "<w:p><w:r><w:t>Confidentiality Period: 5 years.</w:t></w:r></w:p>"
    )
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert result["has_tracked_changes"] is True
    assert result["edit_count"] == 2
    assert result["authors"] == {"Jane Doe": 1, "John Smith": 1}
    assert result["first_date"] == datetime.fromisoformat("2024-01-15T10:00:00+00:00")
    assert result["last_date"] == datetime.fromisoformat("2024-01-16T09:30:00+00:00")

    # base = pre-redline state: has the deleted clause, NOT the inserted date
    assert "This clause is void" in result["base_text"]
    assert "January 1, 2024" not in result["base_text"]
    assert "Confidentiality Period: 5 years." in result["base_text"]

    # proposed = post-redline state: has the inserted date, NOT the deleted clause
    assert "January 1, 2024" in result["proposed_text"]
    assert "This clause is void" not in result["proposed_text"]
    assert "Confidentiality Period: 5 years." in result["proposed_text"]

    kinds = {e["kind"] for e in result["edits"]}
    assert kinds == {"insertion", "deletion"}


def test_inserted_then_deleted_disappears_from_both_renderings():
    # An insertion that was itself deleted before acceptance (nested w:del
    # inside w:ins) never existed in the base document and never survives
    # into the proposed document either.
    body = (
        '<w:p><w:ins w:id="1" w:author="Jane Doe" w:date="2024-01-15T10:00:00Z">'
        '<w:del w:id="2" w:author="Jane Doe" w:date="2024-01-15T10:05:00Z">'
        "<w:r><w:delText>oops typo</w:delText></w:r>"
        "</w:del></w:ins></w:p>"
    )
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert "oops typo" not in result["base_text"]
    assert "oops typo" not in result["proposed_text"]


def test_move_from_and_move_to_treated_as_delete_insert():
    body = (
        '<w:p><w:moveFrom w:id="1" w:author="Jane Doe" w:date="2024-01-15T10:00:00Z">'
        "<w:r><w:t>Moved clause text.</w:t></w:r></w:moveFrom></w:p>"
        '<w:p><w:moveTo w:id="2" w:author="Jane Doe" w:date="2024-01-15T10:00:00Z">'
        "<w:r><w:t>Moved clause text.</w:t></w:r></w:moveTo></w:p>"
    )
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert result["edit_count"] == 2
    kinds = {e["kind"] for e in result["edits"]}
    assert kinds == {"move_from", "move_to"}
    assert result["base_text"].count("Moved clause text.") == 1
    assert result["proposed_text"].count("Moved clause text.") == 1


def test_formatting_only_rprchange_ignored():
    # w:rPrChange records formatting history inside w:rPr — must never be
    # mistaken for a content edit or leak its snapshot text.
    body = (
        "<w:p><w:r>"
        '<w:rPr><w:b/><w:rPrChange w:id="1" w:author="Jane Doe" w:date="2024-01-15T10:00:00Z">'
        "<w:rPr/></w:rPrChange></w:rPr>"
        "<w:t>Bolded text, formatting change only.</w:t>"
        "</w:r></w:p>"
    )
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert result["has_tracked_changes"] is False
    assert result["edit_count"] == 0
    assert "Bolded text, formatting change only." in result["base_text"]
    assert "Bolded text, formatting change only." in result["proposed_text"]


def test_tab_and_line_break_preserved():
    body = "<w:p><w:r><w:t>Col1</w:t><w:tab/><w:t>Col2</w:t><w:br/><w:t>Line2</w:t></w:r></w:p>"
    result = parse_docx_redline(_make_docx(body))
    assert result["ok"] is True
    assert "Col1\tCol2\nLine2" in result["base_text"]


def test_not_a_docx_returns_inconclusive_not_raise():
    result = parse_docx_redline(b"not a zip file at all")
    assert result["ok"] is False
    assert "error" in result


def test_docx_missing_document_xml_returns_inconclusive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not a real docx")
    result = parse_docx_redline(buf.getvalue())
    assert result["ok"] is False


def test_malformed_xml_returns_inconclusive_not_raise():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:document><unclosed>")
    result = parse_docx_redline(buf.getvalue())
    assert result["ok"] is False


def test_real_python_docx_roundtrip_no_tracked_changes():
    # Sanity check against a real docx produced by python-docx (already a
    # project dependency), not only our own hand-built XML fixtures.
    docx = pytest.importorskip("docx")
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("A perfectly normal paragraph with no tracked changes.")
    d.save(buf)
    result = parse_docx_redline(buf.getvalue())
    assert result["ok"] is True
    assert result["has_tracked_changes"] is False
    assert "A perfectly normal paragraph with no tracked changes." in result["base_text"]


def test_pdf_bytes_are_not_a_readable_docx():
    # CobbleStone mislabels some PDFs as .docx (confirmed live: files named
    # "...redline....docx" whose bytes begin %PDF-1.7). The parser must report
    # inconclusive rather than raise; scan_tracked_changes.py sniffs the magic
    # bytes before calling this and routes such files to the PDF check instead.
    result = parse_docx_redline(b"%PDF-1.7\n\n4 0 obj\n<< /Type /Catalog >>\n")
    assert result["ok"] is False
    assert "not a readable docx" in result["error"]
