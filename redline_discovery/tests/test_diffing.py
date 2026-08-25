"""
Regression tests for diffing.py's two audit-flagged bugs:
  1. MIN_CHANGED_WORDS=2 silently dropped every single-word negotiated edit
     (a negation, a changed number, a changed jurisdiction) while claiming
     to only skip whitespace/reflow noise.
  2. MAX_EDITS=40 silently truncated the second half of heavily-negotiated
     documents with no signal that it had happened.
"""

from diffing import diff_documents, MAX_EDITS


def test_single_word_negation_is_kept():
    result = diff_documents(
        "The Supplier shall be liable for damages.",
        "The Supplier shall not be liable for damages.",
    )
    assert any(e["after"] == "not" for e in result["edits"])


def test_single_word_number_change_is_kept():
    result = diff_documents("Payment is due within 30 days.", "Payment is due within 60 days.")
    assert any(e["before"] == "30" and e["after"] == "60" for e in result["edits"])


def test_single_word_jurisdiction_change_is_kept():
    result = diff_documents(
        "This Agreement is governed by the laws of Illinois.",
        "This Agreement is governed by the laws of Delaware.",
    )
    assert any("Illinois" in e["before"] and "Delaware" in e["after"] for e in result["edits"])


def test_pure_whitespace_reflow_is_still_dropped():
    result = diff_documents("word1 word2 word3", "word1  word2 word3")
    assert result["edits"] == []


def test_truncation_flag_set_when_capped():
    orig = " ".join(f"sentence{i} original text here." for i in range(200))
    new = " ".join(f"sentence{i} REPLACED text here." for i in range(200))
    result = diff_documents(orig, new)
    assert len(result["edits"]) == MAX_EDITS
    assert result["truncated"] is True
    assert result["total_edit_opcodes"] > MAX_EDITS


def test_truncation_flag_not_set_when_under_cap():
    result = diff_documents("The rent is $100.", "The rent is $200.")
    assert result["truncated"] is False
    assert result["total_edit_opcodes"] == len(result["edits"])
