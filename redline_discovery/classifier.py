"""
v1 redline classifier — filename heuristics + keyword scan over the
`TextExtract` text CobbleStone already provides on every file record, plus
an email-specific keyword scan for .msg/.eml attachments (playbook Phase 3
technique 4). Also scans CobbleStone's own `Keywords` field (an inconsistently
populated free-text note — sometimes a genuine human summary of the
negotiation, sometimes boilerplate, sometimes blank) with the same signal
lists, since it's the only text CobbleStone provides at all for some
attachments (.msg files routinely have a null TextExtract — OCR/extraction
never completes for them upstream — but occasionally do have Keywords).

Word-XML track-changes and PDF-annotation detection (playbook Phase 3
techniques 2, 3) are handled separately, in structure_check.py — they need
actual file bytes (via request_api.download_file()), which this classifier
deliberately doesn't fetch, staying a pure, network-free function. Legacy
binary .doc files can't go through that check at all (only .docx/.pdf are
supported), so they're flagged here as unverifiable instead of silently
skipped — see LEGACY_UNVERIFIABLE_EXTENSIONS.
"""

import re

FILENAME_HIGH = ["redline", "redlined", "markup", "mark-up", "mark up",
                 "track change", "tracked change"]
FILENAME_MEDIUM = ["draft", "revised", "comment", "review",
                    "negotiated", "negotiation", "negotiating"]
FILENAME_EXECUTED = ["executed", "fully executed", "countersigned",
                      "final signed", "signed copy"]

TEXT_SIGNALS = ["track changes", "for discussion purposes", "subject to change",
                "privileged and confidential", "comment [", "deleted:",
                "inserted:", "redline"]

EDITABLE_EXTENSIONS = {".docx", ".doc"}

# Legacy binary Word (.doc, pre-2007 OLE format) can't be structurally checked
# for track changes the way .docx can (structure_check.py only handles .docx/
# .pdf) — flagged here so it's visibly called out as unverified rather than
# silently invisible. A miss isn't proof of absence, and this file type can't
# even attempt the check.
LEGACY_UNVERIFIABLE_EXTENSIONS = {".doc"}

EMAIL_EXTENSIONS = {".msg", ".eml"}

# Only scanned for files in EMAIL_EXTENSIONS — an email body reads differently
# from a contract draft, and gating these to email attachments only means this
# list can't affect classification of any .docx/.pdf row.
EMAIL_TEXT_SIGNALS = ["please see the attached redline", "attached are our comments",
                      "please find our proposed changes", "mark-up attached",
                      "markup attached", "counsel's comments attached",
                      "revised draft attached", "our proposed revisions",
                      "tracked changes attached"]

_TEXT_SCAN_CHARS = 5000  # keyword scan only needs the first chunk, not the full doc


def _filename_has_keyword(name: str, keyword: str) -> bool:
    # Same normalization as pairing.py's _is_final_executed: underscores/hyphens
    # become spaces so a keyword joined by them (e.g. "SIGNED_Repsol") still gets
    # a real word boundary, and plain substring matches (e.g. "draft" inside
    # "draftsman") no longer false-positive. The trailing "s?" matches plural
    # filenames ("redlines", "track changes", "comments", "markups") without
    # reopening that false-positive: "draftsman" still can't match "drafts?"
    # because there's no boundary between the "s" and "man".
    normalized_name = re.sub(r"[_\-]+", " ", name)
    normalized_kw = re.sub(r"[_\-]+", " ", keyword)
    return re.search(rf"\b{re.escape(normalized_kw)}s?\b", normalized_name) is not None


def _matched_signals(text: str, keyword_list: list) -> list:
    return [kw for kw in keyword_list if kw in text]


def classify_file(file_record: dict) -> dict:
    name = (file_record.get("FileName") or "").lower()
    ext = (file_record.get("FileType") or "").lower()
    text = (file_record.get("TextExtract") or "")[:_TEXT_SCAN_CHARS].lower()
    keywords_field = (file_record.get("Keywords") or "")[:_TEXT_SCAN_CHARS].lower()

    score = 0
    signals = []
    methods = set()

    for kw in FILENAME_HIGH:
        if _filename_has_keyword(name, kw):
            score += 3
            signals.append(f"filename:{kw}")
            methods.add("filename_heuristic")
    for kw in FILENAME_MEDIUM:
        if _filename_has_keyword(name, kw):
            score += 2
            signals.append(f"filename:{kw}")
            methods.add("filename_heuristic")
    for kw in FILENAME_EXECUTED:
        if _filename_has_keyword(name, kw):
            score -= 3
            signals.append(f"filename-negative:{kw}")
            methods.add("filename_heuristic")
    for kw in _matched_signals(text, TEXT_SIGNALS):
        score += 2
        signals.append(f"text:{kw}")
        methods.add("text_heuristic")
    for kw in _matched_signals(keywords_field, TEXT_SIGNALS):
        score += 2
        signals.append(f"keywords:{kw}")
        methods.add("keywords_heuristic")
    if ext in EMAIL_EXTENSIONS:
        for kw in _matched_signals(text, EMAIL_TEXT_SIGNALS):
            score += 2
            signals.append(f"email:{kw}")
            methods.add("email_heuristic")
        for kw in _matched_signals(keywords_field, EMAIL_TEXT_SIGNALS):
            score += 2
            signals.append(f"email-keywords:{kw}")
            methods.add("keywords_heuristic")
    if ext in EDITABLE_EXTENSIONS:
        score += 1
        signals.append("ext:editable")
        methods.add("extension_heuristic")
    if ext in LEGACY_UNVERIFIABLE_EXTENSIONS:
        signals.append("structure_check:unavailable_legacy_format")
        methods.add("legacy_doc_format")

    if score >= 5:
        category = "Redline"
    elif score >= 2:
        category = "Draft/Negotiation Copy"
    elif score <= -2:
        category = "Likely Executed/Signed"
    else:
        category = "Unclassified/Supporting"

    return {
        "category": category,
        "score": score,
        "confidence": min(100, abs(score) * 10),
        "is_likely_redline": category in ("Redline", "Draft/Negotiation Copy"),
        "signals": signals,
        "detection_methods": sorted(methods),
    }
