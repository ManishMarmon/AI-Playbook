"""
v1 redline classifier — filename heuristics + keyword scan over the
`TextExtract` text CobbleStone already provides on every file record.

No download, no Word-XML track-changes parsing, no AI classification yet
(playbook Phase 3 techniques 2, 3, 5) — this is deliberately the cheapest
possible first pass to validate signal quality before building those.
"""

import re

FILENAME_HIGH = ["redline", "redlined", "markup", "mark-up", "mark up",
                 "track change", "tracked change"]
FILENAME_MEDIUM = ["draft", "revised", "comment", "review", "negotiat"]
FILENAME_EXECUTED = ["executed", "fully executed", "countersigned",
                      "final signed", "signed copy"]

TEXT_SIGNALS = ["track changes", "for discussion purposes", "subject to change",
                "privileged and confidential", "comment [", "deleted:",
                "inserted:", "redline"]

EDITABLE_EXTENSIONS = {".docx", ".doc"}

_TEXT_SCAN_CHARS = 5000  # keyword scan only needs the first chunk, not the full doc


def _filename_has_keyword(name: str, keyword: str) -> bool:
    # Same normalization as pairing.py's _is_final_executed: underscores/hyphens
    # become spaces so a keyword joined by them (e.g. "SIGNED_Repsol") still gets
    # a real word boundary, and plain substring matches (e.g. "draft" inside
    # "draftsman") no longer false-positive.
    normalized_name = re.sub(r"[_\-]+", " ", name)
    normalized_kw = re.sub(r"[_\-]+", " ", keyword)
    return re.search(rf"\b{re.escape(normalized_kw)}\b", normalized_name) is not None


def classify_file(file_record: dict) -> dict:
    name = (file_record.get("FileName") or "").lower()
    ext = (file_record.get("FileType") or "").lower()
    text = (file_record.get("TextExtract") or "")[:_TEXT_SCAN_CHARS].lower()

    score = 0
    signals = []

    for kw in FILENAME_HIGH:
        if _filename_has_keyword(name, kw):
            score += 3
            signals.append(f"filename:{kw}")
    for kw in FILENAME_MEDIUM:
        if _filename_has_keyword(name, kw):
            score += 2
            signals.append(f"filename:{kw}")
    for kw in FILENAME_EXECUTED:
        if _filename_has_keyword(name, kw):
            score -= 3
            signals.append(f"filename-negative:{kw}")
    for kw in TEXT_SIGNALS:
        if kw in text:
            score += 2
            signals.append(f"text:{kw}")
    if ext in EDITABLE_EXTENSIONS:
        score += 1
        signals.append("ext:editable")

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
    }
