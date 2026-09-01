"""
Builds each request's diff WITH its comparison basis recorded — the core of
Jeff's 2026-08-31 requirement that every generated rule state whether it came
from an original-to-first-redline comparison (Marmon's preferred negotiating
position) or an original-to-final one (the negotiated compromise).

Where the edits come from, in priority order:

  1. A first-redline .docx's OWN two renderings — base (all tracked changes
     rejected) vs proposed (all accepted), both already stored by
     scan_tracked_changes.py. Basis: REDLINE_INTERNAL, a preferred position.
     This is the best source available and needs no second document: the
     redline file itself contains both sides of that negotiation round, every
     edit in it is a real tracked change rather than text-extraction noise,
     and the markup carries per-edit authorship.

  2. Failing that, a clean original vs the final/executed document. Basis:
     INITIAL_VS_FINAL — the negotiated compromise, both parties' edits mixed
     together. This is Jeff's explicitly-labelled fallback for requests whose
     intermediate documents are missing; it is never presented as a preferred
     position.

  3. Failing that, a single usable document with no comparison available.
     Basis: SINGLE_DOC_BASELINE — evidence that language was accepted as
     signed, not evidence of a negotiating position. No edits, so nothing for
     the diff-based tagger to consume; recorded for completeness.

Output records are the SAME shape run_pairing.py writes (request_id,
edits[{type,before,after,context_before,context_after}], ...) so
azure_clause_tagging.py consumes them with no changes on its side, plus the
new provenance fields (comparison_basis, source_files, edit_authors,
sequence_confidence).

Deterministic and free: reads only what Postgres already holds — no network,
no LLM, no re-downloading or re-parsing of files.
"""

import re

import provenance
from diffing import diff_documents

# Every edit here is a genuine tracked change, not extraction noise, so the
# default cap of 40 (tuned for noisy text-vs-text diffs) would silently drop
# real negotiated language — US NDA redlines average ~47 tracked edits and run
# into the hundreds. Dropping genuine negotiated wording to save prompt size is
# the wrong trade when the point of the exercise is an accurate playbook.
#
# Raised 250 -> 500 on 2026-09-01 when the scope went from the 100 most recent
# mutual NDAs to the whole population. 250 was set from that subset's own
# maximum (228 edits); measured across the classified-mutual population the
# distribution is median 39, p95 108, p99 212, max 356 — so 6 files (0.8%)
# would have been truncated at 250, quietly losing real negotiated language
# from exactly the most heavily-negotiated contracts, which are the most
# informative ones. 500 was set from that pre-classification estimate; the
# actual full-population run then found one request at 572 (9927) with the
# next-heaviest at 290, so 800 now clears the real tail rather than tracking
# it. Truncation is still reported per record (edits_truncated) rather than
# silent, and is asserted to be zero after a run.
MAX_REDLINE_EDITS = 800

# Below this, a "document" is too thin to diff meaningfully (matches
# pairing.MIN_TEXT_CHARS).
MIN_TEXT_CHARS = 200

# Shortest text fragment allowed to establish an author match. Keeps a
# one-or-two-character diff ("a", "of") from matching arbitrary tracked
# changes and manufacturing a false attribution.
_MIN_MATCH_CHARS = 4


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _attribute_authors(edits: list[dict], tracked_edits: list[dict]) -> None:
    """Attach `authors` to each diff edit, in place, by matching the edit's
    text against the tracked-change entries the parser recorded.

    Matching on normalized text rather than character offsets: the parser
    stores each tracked change's text but not its position, and the diff is
    computed from the same two renderings those changes produced, so the text
    of a real tracked change reliably appears in the corresponding diff edit.
    An edit with no confident match is left `unattributed` rather than being
    assigned to whoever edited nearby — a wrong attribution is worse than an
    absent one, since side attribution feeds the preferred-position claim."""
    prepared = [(_norm(t.get("text")), t.get("author"), t.get("date")) for t in tracked_edits or []]
    prepared = [(txt, author, date) for txt, author, date in prepared if len(txt) >= _MIN_MATCH_CHARS]

    for edit in edits:
        # Matching runs BOTH directions on purpose. The word-level diff
        # produces the minimal change ("three" -> "five") while the tracked
        # change carries the fuller run it belonged to ("three years"), so
        # checking only "does the tracked text appear in the edit" misses most
        # real attributions. The length guard keeps a short fragment from
        # matching half the document.
        sides = [_norm(edit.get("before", "")), _norm(edit.get("after", ""))]
        haystack = " ".join(s for s in sides if s)
        candidates = [s for s in sides if len(s) >= _MIN_MATCH_CHARS]
        authors, dates = {}, []
        for txt, author, date in prepared:
            if txt in haystack or any(c in txt for c in candidates):
                if author:
                    authors[author] = authors.get(author, 0) + 1
                if date:
                    dates.append(date)
        edit["authors"] = sorted(authors) if authors else ["unattributed"]
        if dates:
            edit["edit_dates"] = [min(dates), max(dates)]


def _file_record(f: dict, role: str) -> dict:
    return {"file_id": f["id"], "file_name": f["file_name"], "role": role}


# Which redline to diff when a request has several. The earliest round is
# preferred because it is closest to a party's opening ask, but every redline is
# a candidate: whichever one is used, its base-vs-proposed diff is still one
# party's markup for one round, which is what REDLINE_INTERNAL means.
_ROLE_RANK = {"first_redline": 0, "intermediate_redline": 1, "final": 2}


def _redline_rank(f: dict) -> tuple:
    return (_ROLE_RANK.get(f.get("document_role"), 3),
            str(f.get("tracked_change_first_date") or "~"),
            f.get("id") or 0)


def build_request_diff(files: list[dict], request: dict) -> dict:
    """files: rows carrying id, file_name, document_role, sequence_confidence,
    has_tracked_changes, redline_base_text, redline_proposed_text,
    tracked_change_edits, tracked_change_authors, text.
    Returns one record; never raises."""
    record = {
        "request_id": request.get("RequestID"),
        "request_title": request.get("RequestTitle"),
        "vendor": request.get("u_VendorCounterpartyName"),
        "requestor": request.get("u_Requestor"),
        "process_status": request.get("u_RequestProcessStatus"),
        "nda_type": request.get("nda_type"),
        "comparison_basis": None,
        "comparison_basis_label": None,
        "source_files": [],
        "edit_authors": {},
        "sequence_confidence": None,
        "edits": [],
        "edits_truncated": False,
        "total_edit_opcodes": 0,
        "notes": [],
    }

    def finish(basis):
        record["comparison_basis"] = basis
        record["comparison_basis_label"] = provenance.label(basis)
        return record

    # ── 1. Preferred position from a first redline's own renderings ──
    redlines = [f for f in files if f.get("has_tracked_changes")
                and (f.get("redline_base_text") or "") and (f.get("redline_proposed_text") or "")]
    if redlines:
        # Every redline is tried, earliest round first — NOT just the first one.
        # A redline whose base and proposed renderings are textually identical
        # (formatting-only markup, or balanced moves) carries no negotiated
        # language, and stopping there discarded whole requests that held a
        # later redline full of real edits: three requests in the live US mutual
        # NDA subset lost 47, 46 and 79 genuine Marmon-authored tracked changes
        # that way, landing on SINGLE_DOC_BASELINE with nothing to tag.
        chosen = None
        for candidate in sorted(redlines, key=_redline_rank):
            base, proposed = candidate["redline_base_text"], candidate["redline_proposed_text"]
            if _norm(base) != _norm(proposed):
                chosen = candidate
                break
            record["notes"].append(
                f"redline {candidate.get('file_name')!r} "
                f"({candidate.get('document_role') or 'role unknown'}) has textually identical "
                "base and proposed renderings — its tracked changes produced no net text "
                "change (e.g. formatting-only markup or balanced moves), so it was skipped")

        if chosen is not None:
            role = chosen.get("document_role") or "first_redline"
            base, proposed = chosen["redline_base_text"], chosen["redline_proposed_text"]
            result = diff_documents(base, proposed, max_edits=MAX_REDLINE_EDITS)
            _attribute_authors(result["edits"], chosen.get("tracked_change_edits") or [])
            record["edits"] = result["edits"]
            record["edits_truncated"] = result["truncated"]
            record["total_edit_opcodes"] = result["total_edit_opcodes"]
            record["source_files"] = [_file_record(chosen, role)]
            record["edit_authors"] = chosen.get("tracked_change_authors") or {}
            record["sequence_confidence"] = chosen.get("sequence_confidence")
            if role != "first_redline":
                # Kept explicit: a later round has already absorbed some of the
                # other side's changes, so the position it shows is that party's
                # ask at that round, not necessarily its opening one.
                record["notes"].append(
                    f"edits come from the {role.replace('_', ' ')} rather than a first redline, "
                    "so they reflect that party's position at that round of negotiation")
            return finish(provenance.REDLINE_INTERNAL)

    # ── 2. Labelled fallback: original vs final/executed ──
    def usable(f):
        return len(f.get("text") or "") >= MIN_TEXT_CHARS

    original = next((f for f in files if f.get("document_role") == "original" and usable(f)), None)
    later = next((f for f in files if f.get("document_role") == "final" and usable(f)), None)
    if later is None:
        later = next((f for f in files
                      if f.get("document_role") in ("intermediate_redline", "first_redline")
                      and usable(f) and f is not original), None)
    if original is not None and later is not None:
        result = diff_documents(original.get("text") or "", later.get("text") or "")
        for e in result["edits"]:
            e["authors"] = ["unattributed"]
        record["edits"] = result["edits"]
        record["edits_truncated"] = result["truncated"]
        record["total_edit_opcodes"] = result["total_edit_opcodes"]
        record["source_files"] = [_file_record(original, "original"),
                                  _file_record(later, later.get("document_role") or "final")]
        record["sequence_confidence"] = later.get("sequence_confidence")
        record["notes"].append(
            "no usable first-redline markup for this request — edits blend both parties' "
            "changes, so this is an agreed outcome rather than a Marmon preferred position")
        return finish(provenance.INITIAL_VS_FINAL)

    # ── 3. Nothing to compare ──
    usable_docs = [f for f in files if usable(f)]
    if usable_docs:
        sole = usable_docs[0]
        record["source_files"] = [_file_record(sole, sole.get("document_role") or "unknown")]
        # The count is stated rather than assumed: this branch is also reached
        # with SEVERAL usable documents when none of them can be paired (no
        # original/final pair, no redline with a net text change), and calling
        # that "only one usable document" misreported what the request holds.
        record["notes"].append(
            "no comparison possible — one usable document" if len(usable_docs) == 1 else
            f"no comparison possible — {len(usable_docs)} usable documents but no original/final "
            "pair and no redline with a net text change")
        return finish(provenance.SINGLE_DOC_BASELINE)

    record["notes"].append("no usable documents")
    return record
