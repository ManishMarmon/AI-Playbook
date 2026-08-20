"""
Phase 3 techniques 2 & 3 — Word track-changes XML and PDF-annotation
detection, given actual file bytes (see request_api.download_file()).

Pure and network-free: these functions only ever look at bytes already in
hand. Any parse failure (corrupted zip, malformed PDF) is treated as
"inconclusive", never raised — a structural check that can't run is not
evidence of anything, and shouldn't break the caller's loop over hundreds
of files.
"""

import io
import logging
import re
import zipfile

from pypdf import PdfReader

logger = logging.getLogger(__name__)

_TRACK_CHANGE_PATTERN = re.compile(rb"<w:(ins|del)[\s>]")

# Markup annotation subtypes a human reviewer actually left — excludes
# structural types like /Link or /Widget that aren't redline commentary.
_MARKUP_ANNOTATION_SUBTYPES = {"/Highlight", "/StrikeOut", "/Underline",
                                "/Squiggly", "/Text", "/FreeText"}


def has_docx_track_changes(file_bytes: bytes) -> tuple[bool, int]:
    """Scans every word/*.xml part of a .docx (it's a zip archive) for
    <w:ins>/<w:del> — Word's track-changes markup. A plain byte-pattern
    count is robust enough here and avoids a namespace-aware XML dependency
    for what's ultimately just tag-name detection."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            count = 0
            for name in zf.namelist():
                if name.startswith("word/") and name.endswith(".xml"):
                    count += len(_TRACK_CHANGE_PATTERN.findall(zf.read(name)))
            return count > 0, count
    except (zipfile.BadZipFile, KeyError) as e:
        logger.warning(f"has_docx_track_changes: couldn't parse file as docx zip: {e}")
        return False, 0


def has_pdf_annotations(file_bytes: bytes) -> tuple[bool, int]:
    """Counts markup-relevant annotation objects (highlights, strikeouts,
    comments, etc.) across all pages — the PDF equivalent of track changes."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        count = 0
        for page in reader.pages:
            annots = page.get("/Annots")
            if not annots:
                continue
            for ref in annots:
                annot = ref.get_object()
                if annot.get("/Subtype") in _MARKUP_ANNOTATION_SUBTYPES:
                    count += 1
        return count > 0, count
    except Exception as e:
        # pypdf can raise a variety of exception types on malformed PDFs
        # (not just its own PdfReadError) — any of them means "inconclusive".
        logger.warning(f"has_pdf_annotations: couldn't parse file as PDF: {e}")
        return False, 0


def check_file_structure(file_type: str, file_bytes: bytes) -> dict | None:
    """Single entry point for run_discovery.py. Returns None if the file
    type isn't supported or no markup was found — a miss here means "fall
    through to the AI-classification fallback", not "confirmed not a redline"."""
    if file_type == ".docx":
        found, count = has_docx_track_changes(file_bytes)
        if found:
            return {"detection_method": "track_changes_xml",
                     "signal": f"track_changes:{count} tracked edits found"}
    elif file_type == ".pdf":
        found, count = has_pdf_annotations(file_bytes)
        if found:
            return {"detection_method": "pdf_annotation",
                     "signal": f"pdf_annotation:{count} markup annotations found"}
    return None
