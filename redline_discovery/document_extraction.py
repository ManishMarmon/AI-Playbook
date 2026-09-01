"""
Local text extraction for .pdf/.docx/.xlsx — recovers real document text from
raw file bytes, bypassing CobbleStone's own TextExtract field entirely.

Confirmed live (see repair_text_extraction.py's investigation): CobbleStone's
extraction has been broken across EVERY file type since ~2023 (near-100%
empty by 2025-2026) — not a format-specific gap, a service-level one. The
underlying documents are completely intact; downloading them directly (see
request_api.download_file()) and extracting locally recovers real text every
time a text layer actually exists in the file.

Known, accepted limitation: pypdf reads a PDF's embedded text layer only —
it does not OCR. A pure scanned image with no text layer yields "" here, the
same as CobbleStone's own (also non-OCR) extraction would. .doc (legacy
binary OLE format, distinct from .docx's zip/XML format) and .zip aren't
handled here — lower volume than .pdf/.docx/.xlsx and need a different
approach (Word COM automation or a binary-format parser); a real, known gap,
not silently pretended away.
"""

import io
import logging
import re
import zipfile

import pypdf
import openpyxl

logger = logging.getLogger(__name__)


def _extract_pdf_text(raw_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _extract_docx_text(raw_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    # A real text extraction, not a full XML parse: <w:p> paragraph ends need
    # to become newlines BEFORE tag-stripping, or paragraph/sentence
    # boundaries fuse into one run-on line with no word-diff-usable structure.
    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_xlsx_text(raw_bytes: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
    lines = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


def _extract_rtf_text(raw_bytes: bytes) -> str:
    # Not a real RTF parser — strips control words/groups well enough for
    # plain prose, which is all diffing/tagging actually needs. Adequate for
    # the ~30 real .rtf files seen live; not attempting embedded objects,
    # tables, or field codes.
    text = raw_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)  # \'e9-style hex escapes
    text = re.sub(r"\{\\\*?\\[^{}]*\}", " ", text)   # destination groups (fonttbl, colortbl, ...)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)  # control words
    text = re.sub(r"[{}]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


_EXTRACTORS = {
    ".pdf": _extract_pdf_text,
    ".docx": _extract_docx_text,
    ".docm": _extract_docx_text,   # same zip/XML structure as .docx, macro-enabled
    ".dotx": _extract_docx_text,   # same structure, template variant
    ".xlsx": _extract_xlsx_text,
    ".xlsm": _extract_xlsx_text,   # same structure as .xlsx, macro-enabled
    ".rtf": _extract_rtf_text,
}


def extract_document_text(raw_bytes: bytes, file_type: str) -> str:
    """Returns "" (never raises) if the type is unsupported or parsing
    fails — same "no signal available" convention as
    request_api.download_file() and msg_extraction.extract_email_text()."""
    extractor = _EXTRACTORS.get((file_type or "").lower())
    if not extractor:
        return ""
    try:
        return extractor(raw_bytes)
    except Exception as e:
        logger.warning(f"extract_document_text failed for {file_type} file: {e}")
        return ""
