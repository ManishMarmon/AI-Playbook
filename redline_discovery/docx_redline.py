"""
Full Word tracked-changes parser — extends structure_check.py's detection
(presence + count via a byte-pattern scan) into full extraction: per-edit
author, timestamp, and two derived whole-document text renderings.

Why two renderings from ONE file matter (Jeff's guidance, 2026-08-31): a
single redlined .docx already contains BOTH states of the negotiation round
it represents — "base" (all tracked changes rejected) is what the document
looked like walking in, "proposed" (all tracked changes accepted) is what
it looked like walking out. Diffing base-vs-proposed on ONE file reproduces
an initial-vs-first-redline comparison even when the clean, unmarked
"initial" document was never separately uploaded to CobbleStone — which is
common: the earliest surviving artifact of a negotiation is very often
already the counterparty's or Marmon's first redline.

Scope, deliberately: word/document.xml only (not headers/footers/footnotes)
— contract clause language lives in the body, and header/footer content is
almost never substantive redline material. Formatting-only change tracking
(w:rPrChange, w:pPrChange, and table/section property-change equivalents)
is ignored on purpose: it records style history, not text content, and
never contributes to base/proposed text or the edit list. w:moveFrom /
w:moveTo (Word's tracked "move text" markup) are treated as deletion/
insertion respectively for text-reconstruction purposes — a move is, from a
pure base-vs-proposed text standpoint, exactly a delete-from-here plus an
insert-there.

Known imprecision, accepted: an individually tracked PARAGRAPH MARK
(inserting/deleting the paragraph break itself, as opposed to its text) can
make base/proposed paragraph boundaries differ slightly from Word's own
reconstruction in rare paragraph-split/merge edits. Word count and
paragraph-exact layout are not the goal here — the words present in each
rendering are still correct, which is what clause-level LLM diffing needs.

Pure and network-free, like structure_check.py: operates only on bytes
already in hand, never raises — a parse failure returns an "inconclusive"
result (ok=False), not an exception, since callers loop over hundreds of
files and one malformed one must not break the batch.
"""

import io
import logging
import zipfile
from collections import Counter
from datetime import datetime
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_INS_LIKE = {"ins", "moveTo"}
_DEL_LIKE = {"del", "moveFrom"}
_EDIT_KIND = {"ins": "insertion", "del": "deletion", "moveFrom": "move_from", "moveTo": "move_to"}
# Property containers: never hold body text, and this is what keeps
# formatting-only change tracking (w:rPrChange etc., which nests a snapshot
# <w:rPr> inside itself) from ever being mistaken for real content — we
# simply never descend into any *Pr element at all.
_SKIP_SUBTREE = {"rPr", "pPr", "sectPr", "tblPr", "tblGrid", "trPr", "tcPr"}
_TEXT_TAGS = {"t", "delText"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_w_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Walker:
    """Single recursive pass over word/document.xml that simultaneously
    builds (1) the base and proposed text renderings and (2) the flat list
    of top-level (non-nested) tracked-change edits. One pass, not two, so
    the two outputs can never disagree with each other about what an edit
    contains."""

    def __init__(self):
        self.base_parts: list[str] = []
        self.proposed_parts: list[str] = []
        self.edits: list[dict] = []
        self._edit_stack: list[dict | None] = []  # None = nested (non-top-level) wrapper
        self._in_ins = 0
        self._in_del = 0

    def _emit(self, text: str):
        if not text:
            return
        if self._in_ins and self._in_del:
            pass  # inserted then deleted before acceptance — never in either final state
        elif self._in_ins:
            self.proposed_parts.append(text)
        elif self._in_del:
            self.base_parts.append(text)
        else:
            self.base_parts.append(text)
            self.proposed_parts.append(text)
        for edit in reversed(self._edit_stack):
            if edit is not None:
                edit["_text_parts"].append(text)
                break

    def walk(self, el: ET.Element):
        tag = _local(el.tag)
        if tag in _SKIP_SUBTREE:
            return

        is_wrapper = tag in _INS_LIKE or tag in _DEL_LIKE
        if is_wrapper:
            if self._edit_stack:
                self._edit_stack.append(None)  # nested — text still counted, not a separate top-level edit
            else:
                self._edit_stack.append({
                    "author": el.get(f"{W_NS}author"),
                    "date": _parse_w_date(el.get(f"{W_NS}date")),
                    "kind": _EDIT_KIND[tag],
                    "_text_parts": [],
                })
            if tag in _INS_LIKE:
                self._in_ins += 1
            else:
                self._in_del += 1

        if tag in _TEXT_TAGS:
            self._emit(el.text or "")
        elif tag == "tab":
            self._emit("\t")
        elif tag in ("br", "cr"):
            self._emit("\n")

        for child in el:
            self.walk(child)

        if tag == "p":
            self.base_parts.append("\n")
            self.proposed_parts.append("\n")

        if is_wrapper:
            if tag in _INS_LIKE:
                self._in_ins -= 1
            else:
                self._in_del -= 1
            finished = self._edit_stack.pop()
            if finished is not None:
                finished["text"] = "".join(finished.pop("_text_parts"))
                self.edits.append(finished)


def parse_docx_redline(file_bytes: bytes) -> dict:
    """Returns a dict, always — never raises.

    On success: {"ok": True, "has_tracked_changes": bool, "edit_count": int,
    "authors": {name: count}, "first_date": datetime|None,
    "last_date": datetime|None, "edits": [{"author", "date", "kind", "text"}],
    "base_text": str, "proposed_text": str}

    On failure (not a valid docx / malformed XML): {"ok": False, "error": str}
    — inconclusive, not "confirmed no tracked changes"."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        return {"ok": False, "error": f"not a readable docx: {e}"}

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return {"ok": False, "error": f"malformed document.xml: {e}"}

    walker = _Walker()
    try:
        walker.walk(root)
    except Exception as e:  # defensive — a single malformed file must never kill a batch
        logger.warning(f"parse_docx_redline: unexpected error walking document.xml: {e}")
        return {"ok": False, "error": f"walk failed: {e}"}

    dates = [e["date"] for e in walker.edits if e["date"] is not None]
    return {
        "ok": True,
        "has_tracked_changes": len(walker.edits) > 0,
        "edit_count": len(walker.edits),
        "authors": dict(Counter(e["author"] for e in walker.edits if e["author"])),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "edits": walker.edits,
        "base_text": "".join(walker.base_parts),
        "proposed_text": "".join(walker.proposed_parts),
    }
