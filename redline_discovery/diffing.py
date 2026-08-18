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
MIN_CHANGED_WORDS = 2    # skip single-word/whitespace-only noise
MAX_EDITS = 40           # cap per pair — avoids drowning in trivial reflow diffs


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\S+|\s+", text or "")


def diff_documents(original_text: str, redline_text: str) -> list[dict]:
    orig_tokens = _tokenize(original_text)
    new_tokens = _tokenize(redline_text)
    matcher = difflib.SequenceMatcher(None, orig_tokens, new_tokens, autojunk=False)

    edits = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = "".join(orig_tokens[i1:i2]).strip()
        after = "".join(new_tokens[j1:j2]).strip()
        if len(before.split()) < MIN_CHANGED_WORDS and len(after.split()) < MIN_CHANGED_WORDS:
            continue

        context_before = "".join(orig_tokens[max(0, i1 - CONTEXT_WORDS * 2):i1]).strip()
        context_after = "".join(orig_tokens[i2:i2 + CONTEXT_WORDS * 2]).strip()

        edits.append({
            "type": tag,  # 'replace', 'delete', or 'insert'
            "before": before,
            "after": after,
            "context_before": context_before[-300:],
            "context_after": context_after[:300],
        })
        if len(edits) >= MAX_EDITS:
            break

    return edits
