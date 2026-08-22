"""
B2 (Golden Rules review) — per-request playbook selection and review-text
selection. Pure logic, no API calls — mirrors classifier.py/structure_check.py's
convention of keeping this kind of decision network-free and independently
testable.

Two separate questions, deliberately not conflated:
- select_playbook(): WHICH playbook governs this request at all (business_sector
  crosswalk — a deterministic business fact, not a judgment call).
- select_review_text(): WHICH file's text is the "current state" to check
  against that playbook's rules, once we know one applies.

CobbleStone's own contract_type (u_RequestType) does NOT reliably identify which
requests a given playbook governs — confirmed live, of the 23 business_sector ==
"Crane" requests (Freo Group AU's actual business line) in a 100-request sample,
14 were filed under contract_type "General", not "Equipment Leasing". business_sector
is the crosswalk key; contract_type is not.
"""

import re

from pairing import _is_final_executed, _usable

MAX_REVIEW_TEXT_CHARS = 300_000  # p90 real TextExtract length is ~93K chars;
# this is a generous cap against the rare pathological outlier, not a typical case.

# select_review_text() picks exactly ONE file per request as "the contract" —
# real CobbleStone requests routinely carry 10-17 attached files (a live example:
# request 263, 17 files). The other files are never read. Checked live against
# that example rather than assumed: the ones NOT selected were either (a) an
# unfilled boilerplate exhibit — e.g. a "Compensation Agreement" template still
# containing "[Sterling Crane LLC]", "{INSERT SCOPE OF WORK}", "CWxxxxxx" — where
# skipping it is correct, since it isn't this deal's actual terms, or (b) a real,
# filled-in file (an equipment rate sheet with actual dollar figures) that WAS
# missed. Rather than guessing which category a file falls into and silently
# dropping the ones that don't look interesting, catalog_other_files() below
# reports every non-selected file's template-likelihood as a fact, so a human
# or a future feature can decide — this script never claims full coverage it
# didn't actually deliver.
_TEMPLATE_PATTERNS = [
    re.compile(r"\{INSERT[^}]{0,80}\}", re.IGNORECASE),   # {INSERT SCOPE OF WORK}
    re.compile(r"\[\s*Insert\b[^\]]{0,80}\]", re.IGNORECASE),  # [Insert Company Name]
    re.compile(r"\bMM/DD/YYYY\b"),                         # unfilled date field
    re.compile(r"\b[A-Z]{2,5}xxxxxx\b"),                   # CWxxxxxx-style blanked contract number
    re.compile(r"\bxxx-xxx-xxxx\b"),                       # blanked phone number
]
_TEMPLATE_MATCH_THRESHOLD = 2  # a single incidental match isn't enough evidence;
# real unfilled templates repeat these markers throughout the document.


def _looks_like_template(text: str) -> bool:
    """True if `text` reads like an unfilled boilerplate form rather than this
    deal's actual executed terms. Deliberately conservative (generic placeholder
    syntax only, not "reuses words from the main contract") to avoid excluding
    a real filled-in exhibit by mistake — false negatives (missing a real
    template) are safer here than false positives (hiding a real file)."""
    sample = text[:20_000]  # placeholders cluster near the top of a form; no need to scan 100K+ chars
    hits = sum(len(p.findall(sample)) for p in _TEMPLATE_PATTERNS)
    return hits >= _TEMPLATE_MATCH_THRESHOLD


def catalog_other_files(files: list[dict], selected_file_id: int | None) -> list[dict]:
    """Every usable file NOT selected as the review text, with an honest
    template-likelihood flag on each — never silently dropped from the record."""
    return [
        {
            "file_id": f.get("ID"),
            "file_name": f.get("FileName"),
            "file_type": f.get("FileType"),
            "char_count": len(f.get("TextExtract") or ""),
            "looks_like_template": _looks_like_template(f.get("TextExtract") or ""),
        }
        for f in files
        if _usable(f) and f.get("ID") != selected_file_id
    ]


def select_playbook(business_sector: str | None, manifest: list[dict]) -> dict:
    """Returns {playbook_id, reason} — playbook_id is None (with a reason) when
    zero or more-than-one manifest entries claim this business_sector. Never
    guesses: a wrong playbook match is worse than no match at all."""
    if not business_sector:
        return {"playbook_id": None, "reason": "no_business_sector"}

    matches = [
        entry for entry in manifest
        if business_sector in (entry.get("businessSectors") or [])
    ]
    if len(matches) == 0:
        return {"playbook_id": None, "reason": "no_matching_playbook"}
    if len(matches) > 1:
        return {"playbook_id": None, "reason": "ambiguous_playbook_match"}
    return {"playbook_id": matches[0]["id"], "reason": None}


def select_review_text(request: dict, files: list[dict], pairing_result: dict) -> dict:
    """Picks the file whose text best represents this contract's CURRENT state
    to check against the rules, independent of whether it was ever negotiated:

    1. The final-executed file, if one exists — the signed text is more
       authoritative for a compliance check than an in-progress redline.
    2. Else pairing_result's "redline" side, when a real (original, redline)
       pair was found.
    3. Else, if pairing failed ("insufficient_files") but exactly one usable
       file remains — accepted as-is, never negotiated, so pairing had nothing
       to pair it against. This is the case Phase 5's diff-based findings are
       structurally blind to, and the whole reason B2 can't be built on top of
       them: a rule violation here produces zero diff opcodes.
    4. Else nothing usable exists for this request.
    """
    final_executed_name = pairing_result.get("final_executed_file")
    if final_executed_name:
        final_executed = next(
            (f for f in files if f.get("FileName") == final_executed_name and _usable(f)),
            None,
        )
        if final_executed:
            return _build_result(final_executed, "final_executed")

    redline = pairing_result.get("redline")
    if redline and _usable(redline):
        return _build_result(redline, "pairing_redline")

    if pairing_result.get("method") == "insufficient_files":
        usable = [f for f in files if _usable(f) and not _is_final_executed(f)]
        if len(usable) == 1:
            return _build_result(usable[0], "sole_unnegotiated_file")

    return {"text": "", "file_name": None, "file_id": None, "source": "none", "char_count": 0}


def _build_result(f: dict, source: str) -> dict:
    text = f.get("TextExtract") or ""
    truncated = len(text) > MAX_REVIEW_TEXT_CHARS
    return {
        "text": text[:MAX_REVIEW_TEXT_CHARS],
        "file_name": f.get("FileName"),
        "file_id": f.get("ID"),
        "source": source,
        "char_count": len(text),
        "truncated": truncated,
    }
