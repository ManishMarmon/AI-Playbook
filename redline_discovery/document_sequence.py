"""
Per-request document sequencing — assigns each usable file a role in the
negotiation's progression: original -> first_redline -> intermediate_redline
-> final.

Why this exists (Jeff, 2026-08-31): the pipeline previously picked exactly
two files per request and diffed them, with no notion of WHICH negotiation
round each represented. That conflates two legally different things — a
diff of original-vs-final captures the negotiated COMPROMISE (both sides'
edits mixed together), while original-vs-first-redline captures MARMON'S
PREFERRED POSITION. A playbook should teach the preferred position, so we
must know which files are which. Jeff also noted that document dates and
edit history can establish the revision sequence — that is exactly what
this module consumes.

Signal priority, strongest first:
  1. Tracked-changes markup (files.has_tracked_changes + internal w:date
     range from docx_redline.py). A file carrying tracked changes IS a
     redline round, which is direct evidence rather than inference — and
     its internal edit dates order rounds even when upload dates don't.
  2. Executed/signed filename markers (reusing pairing.py's vetted
     _EXECUTED_FILENAME_MARKERS taxonomy) -> final.
  3. Upload chronology (EntryDate).

Confidence is reported, never hidden: 'high' when tracked-changes evidence
carried the assignment, 'medium' for filename+chronology inference, 'low'
when the request's documents look mutually unrelated (see below) or the
evidence is too thin to distinguish rounds.

The mispairing trap, guarded explicitly: two textually DIFFERENT documents
in one request (e.g. two distinct amendments, or an NDA plus an unrelated
order form — request 264 was a real live example) must never be sequenced
as successive rounds of one negotiation. Roles are still reported, but
confidence drops to 'low' with the reason recorded, so a downstream
consumer can refuse to derive a preferred-position diff from them.

Pure and network-free: consumes file dicts already in hand (CobbleStone
API shape plus the scan columns db.get_files_for_request merges in).
"""

import difflib
import re

from pairing import MIN_TEXT_CHARS, _is_final_executed

# Below this word-level similarity, two documents are probably not the same
# contract at different stages. Matches azure_supplementary_findings.py's
# SAME_DOCUMENT_SIMILARITY_THRESHOLD (0.5), which was calibrated live after
# duplicate-round pollution produced 882 spurious findings.
SAME_DOCUMENT_SIMILARITY_THRESHOLD = 0.5

ROLE_ORIGINAL = "original"
ROLE_FIRST_REDLINE = "first_redline"
ROLE_INTERMEDIATE_REDLINE = "intermediate_redline"
ROLE_FINAL = "final"


def _usable(f: dict) -> bool:
    """Usable for sequencing. Note this is deliberately broader than
    pairing._usable(): a tracked-changes docx qualifies on markup alone even
    if its extracted text is thin, because the markup itself is the evidence
    we care about and the real text lives in base/proposed renderings."""
    if f.get("has_tracked_changes"):
        return True
    return len(f.get("TextExtract") or "") >= MIN_TEXT_CHARS


def _similarity(a: str, b: str) -> float:
    wa = re.findall(r"\S+", a or "")
    wb = re.findall(r"\S+", b or "")
    if not wa or not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).quick_ratio()


def _sort_key(f: dict):
    """Order by the earliest evidence of when the file's edits happened,
    falling back to upload date. Tracked-change dates are preferred because
    they describe the negotiation round itself rather than when someone got
    around to uploading it (Jeff's edit-history point)."""
    tc_first = f.get("tracked_change_first_date")
    entry = f.get("EntryDate")
    # Normalize to a comparable string; None sorts last.
    primary = str(tc_first) if tc_first else ""
    secondary = str(entry) if entry else ""
    return (primary == "" and secondary == "", primary or secondary, secondary)


def sequence_documents(files: list[dict]) -> dict:
    """Returns:
      {"roles": {file_id: {"role", "confidence", "reasoning"}},
       "ordered": [file dicts in negotiation order],
       "has_redline_evidence": bool,
       "request_confidence": "high"|"medium"|"low",
       "notes": [str]}

    Never raises. A request with nothing usable returns empty roles."""
    usable = [f for f in files if _usable(f)]
    notes: list[str] = []

    if not usable:
        return {"roles": {}, "ordered": [], "has_redline_evidence": False,
                "request_confidence": "low", "notes": ["no usable files"]}

    redlines = [f for f in usable if f.get("has_tracked_changes")]
    has_redline_evidence = bool(redlines)

    # ── Cohesion check: do these documents even belong to one negotiation? ──
    # Compare each file's best available text against the largest file's.
    # Tracked-changes files are compared on their base text when the caller
    # supplied it (scan_tracked_changes stores only metadata, so callers that
    # want this precision pass base_text through); otherwise TextExtract.
    def best_text(f: dict) -> str:
        return f.get("base_text") or f.get("TextExtract") or ""

    anchor = max(usable, key=lambda f: len(best_text(f)))
    unrelated = []
    for f in usable:
        if f is anchor:
            continue
        sim = _similarity(best_text(anchor), best_text(f))
        if sim < SAME_DOCUMENT_SIMILARITY_THRESHOLD and len(best_text(f)) >= MIN_TEXT_CHARS:
            unrelated.append((f, sim))
    cohesive = not unrelated
    if unrelated:
        notes.append(
            f"{len(unrelated)} file(s) are <{SAME_DOCUMENT_SIMILARITY_THRESHOLD} similar to the "
            f"largest document — these may be distinct agreements rather than negotiation rounds, "
            f"so sequencing is not trustworthy for deriving a preferred-position diff"
        )

    ordered = sorted(usable, key=_sort_key)

    # ── Role assignment ──
    finals = [f for f in ordered if _is_final_executed(f)]
    final_file = finals[-1] if finals else None

    roles: dict = {}
    base_confidence = "high" if has_redline_evidence else "medium"
    if not cohesive:
        base_confidence = "low"

    if final_file is not None:
        roles[final_file["ID"]] = {
            "role": ROLE_FINAL,
            "confidence": base_confidence if cohesive else "low",
            "reasoning": "filename carries an executed/signed marker",
        }

    remaining = [f for f in ordered if f is not final_file]
    redline_seen = False
    for f in remaining:
        fid = f["ID"]
        if f.get("has_tracked_changes"):
            role = ROLE_FIRST_REDLINE if not redline_seen else ROLE_INTERMEDIATE_REDLINE
            authors = f.get("tracked_change_authors") or {}
            author_note = f" by {', '.join(list(authors)[:3])}" if authors else ""
            reasoning = (f"{f.get('tracked_change_count') or 0} tracked edits{author_note}; "
                         f"{'earliest' if not redline_seen else 'later'} redline round by edit date")
            roles[fid] = {"role": role, "confidence": base_confidence, "reasoning": reasoning}
            redline_seen = True
        else:
            # A clean (unmarked) document. Before the first redline it is the
            # original; after one, it is most likely a clean regeneration of a
            # negotiated round rather than a fresh starting point.
            if not redline_seen:
                roles[fid] = {
                    "role": ROLE_ORIGINAL,
                    "confidence": ("high" if (has_redline_evidence and cohesive)
                                   else ("medium" if cohesive else "low")),
                    "reasoning": "no tracked changes and precedes the first redline round",
                }
            else:
                roles[fid] = {
                    "role": ROLE_INTERMEDIATE_REDLINE,
                    "confidence": "low",
                    "reasoning": ("clean document appearing after a redline round — could be an "
                                  "accepted-changes regeneration; role is inferred, not evidenced"),
                }

    if not cohesive:
        for f, sim in unrelated:
            if f["ID"] in roles:
                roles[f["ID"]]["confidence"] = "low"
                roles[f["ID"]]["reasoning"] += f"; only {sim:.2f} similar to the request's main document"

    request_confidence = base_confidence
    if has_redline_evidence and cohesive and any(
            r["role"] == ROLE_ORIGINAL for r in roles.values()):
        request_confidence = "high"

    return {
        "roles": roles,
        "ordered": ordered,
        "has_redline_evidence": has_redline_evidence,
        "request_confidence": request_confidence,
        "notes": notes,
    }
