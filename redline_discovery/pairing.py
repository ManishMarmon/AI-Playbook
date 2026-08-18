"""
File pairing — for a request with multiple attachments, identify which file
is the ORIGINAL (as submitted) and which is the REDLINE (as negotiated),
so they can be diffed against each other.

Signal, validated against live data (RequestID 87 and 20062): the file
uploaded by the employee matching the request's `u_HandlingAttorney` is
reliably the redline/reviewed copy; the file uploaded by the original
requestor (`EnteredBy` / `EmployeeContactID`) is reliably the original.
Falls back to upload-chronology (earliest = original, latest = redline)
when the attorney-match signal isn't available.
"""

import difflib
import re

MIN_TEXT_CHARS = 200  # files with less extracted text than this aren't worth diffing

# Calibrated on 5 live examples, not a validated cutoff: known-good same-document
# redline pairs scored 0.86-0.99 similarity; two pairs that turned out to be
# genuinely different documents (an unrelated Order Form, a different year's
# agreement) scored 0.35 and 0.58. There's real signal here but not enough
# examples to trust a hard reject threshold, so this only WARNS — it doesn't
# drop the pair. A human (or a later, better-calibrated pass) should be the
# one deciding whether a low-similarity pair is still worth its diff.
LOW_SIMILARITY_WARNING_THRESHOLD = 0.6

# A file matching these is the FINAL signed copy, not a negotiation markup —
# diffing "original vs. this" mislabels a template-vs-final comparison (which
# includes signature-block/PDF-encoding noise) as a "redline" edit. Same
# taxonomy as classifier.py's FILENAME_EXECUTED / EXECUTION_KEYWORDS_MEDIUM in
# config.py. "signed" is standalone (not just "signed copy") — caught live on
# request 94: "SIGNED_Repsol_Edson Agreement...Final Version.pdf" slipped
# through the original phrase-only list and got mislabeled as a redline.
_EXECUTED_FILENAME_MARKERS = ["executed", "countersigned", "fully executed",
                              "fully-executed", "signed", "final version"]


def _usable(f: dict) -> bool:
    return len(f.get("TextExtract") or "") >= MIN_TEXT_CHARS


def _is_final_executed(f: dict) -> bool:
    # Underscores/hyphens normalized to spaces first so "SIGNED_Repsol" gets a
    # real word boundary around "signed" — \b alone treats '_' as a word char
    # and would miss it. "unsigned" still correctly does NOT match: there's no
    # separator between "un" and "signed" to normalize, so the two stay fused
    # with no word boundary between them.
    name = re.sub(r"[_\-]+", " ", (f.get("FileName") or "").lower())
    return any(re.search(rf"\b{re.escape(marker)}\b", name) for marker in _EXECUTED_FILENAME_MARKERS)


def pair_files(request: dict, files: list[dict]) -> dict:
    usable = [f for f in files if _usable(f)]
    usable.sort(key=lambda f: f.get("EntryDate") or "")

    # Exclude EVERY file matching the executed markers, not just one instance —
    # a duplicate re-upload of the same final PDF (seen live: same filename,
    # two different file IDs) would otherwise leave one copy sitting in
    # `candidates`, where it gets mislabeled as the "redline".
    final_executed = next((f for f in reversed(usable) if _is_final_executed(f)), None)
    candidates = [f for f in usable if not _is_final_executed(f)]

    if len(candidates) < 2:
        return {"original": None, "redline": None, "method": "insufficient_files",
                "file_count": len(usable), "total_file_count": len(files),
                "final_executed_file": final_executed.get("FileName") if final_executed else None,
                "similarity": None, "low_similarity_warning": False}

    attorney_id = request.get("u_HandlingAttorney")
    entered_by = request.get("EnteredBy") or request.get("EmployeeContactID")

    redline = None
    if attorney_id:
        attorney_files = [f for f in candidates if f.get("EmployeeID") == attorney_id]
        if attorney_files:
            redline = attorney_files[-1]  # latest, in case of multiple revisions

    original = None
    if entered_by:
        requestor_files = [f for f in candidates if f.get("EmployeeID") == entered_by]
        if requestor_files:
            original = requestor_files[0]  # earliest

    method_parts = []
    if redline is not None:
        method_parts.append("attorney_match")
    if original is not None:
        method_parts.append("requestor_match")

    # Fallback: fill in whichever side is still missing using chronology,
    # excluding whatever's already been assigned to the other side.
    remaining = [f for f in candidates if f is not original and f is not redline]
    if original is None and remaining:
        original = remaining[0]
        method_parts.append("chronology_fallback_original")
    if redline is None and remaining:
        later = [f for f in remaining if f is not original]
        if later:
            redline = later[-1]
            method_parts.append("chronology_fallback_redline")

    if original is redline:
        redline = None

    similarity = None
    if original and redline:
        a = re.findall(r"\S+", original.get("TextExtract") or "")
        b = re.findall(r"\S+", redline.get("TextExtract") or "")
        similarity = difflib.SequenceMatcher(None, a, b, autojunk=False).quick_ratio()

    return {
        "original": original,
        "redline": redline,
        "method": "+".join(method_parts) or "none",
        "file_count": len(usable),
        "total_file_count": len(files),
        "final_executed_file": final_executed.get("FileName") if final_executed else None,
        "similarity": round(similarity, 3) if similarity is not None else None,
        "low_similarity_warning": similarity is not None and similarity < LOW_SIMILARITY_WARNING_THRESHOLD,
    }
