"""
Word-level diff between an original and redlined document's already-provided
TextExtract, producing edits with surrounding context (location + spirit of
what changed) — e.g. "Preamble deleted lines" or a "Permitted Disclosure"
edit, per the playbook's Phase 4 goal, without needing to download or parse
the files themselves.
"""

import difflib
import re

CONTEXT_WORDS = 12       # words of surrounding context kept on each side
MAX_EDITS = 40           # cap per pair — avoids drowning in trivial reflow diffs


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\S+|\s+", text or "")


def diff_documents(original_text: str, redline_text: str, max_edits: int = MAX_EDITS) -> dict:
    """max_edits caps how many edits are kept (the rest are counted but not
    returned, and `truncated` reports it). The default 40 suits a noisy
    text-vs-text diff of two separately-extracted documents. Callers diffing a
    redline's own base-vs-proposed renderings — where every edit is a real
    tracked change rather than extraction noise — should raise it: US NDA
    redlines average ~47 tracked edits, so 40 would silently drop genuine
    negotiated language (see provenance_diff.py)."""
    orig_tokens = _tokenize(original_text)
    new_tokens = _tokenize(redline_text)
    matcher = difflib.SequenceMatcher(None, orig_tokens, new_tokens, autojunk=False)

    edits = []
    total_real_opcodes = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = "".join(orig_tokens[i1:i2]).strip()
        after = "".join(new_tokens[j1:j2]).strip()
        # Only skip a genuinely no-op change (e.g. whitespace/line-wrap reflow
        # where both sides strip to nothing) — a single real word (a negation,
        # a number, a jurisdiction name) is exactly the kind of high-signal
        # negotiated edit this pipeline exists to catch, so it must not be
        # dropped just for being short.
        if not before and not after:
            continue
        total_real_opcodes += 1

        context_before = "".join(orig_tokens[max(0, i1 - CONTEXT_WORDS * 2):i1]).strip()
        context_after = "".join(orig_tokens[i2:i2 + CONTEXT_WORDS * 2]).strip()

        if len(edits) < max_edits:
            edits.append({
                "type": tag,  # 'replace', 'delete', or 'insert'
                "before": before,
                "after": after,
                "context_before": context_before[-300:],
                "context_after": context_after[:300],
            })

    return {
        "edits": edits,
        "truncated": total_real_opcodes > len(edits),
        "total_edit_opcodes": total_real_opcodes,
    }
