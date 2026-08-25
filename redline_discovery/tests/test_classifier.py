"""
Regression tests for classifier.py's two audit-flagged \b-boundary bugs:
  1. plural filenames ("redlines", "track changes", "comments", "markups")
     never matched their singular keyword entries.
  2. the "negotiat" stem could never match anything at all, since \b requires
     a real word boundary right after "t" and none of negotiated/negotiation/
     negotiating have one there.
Both are fixed in classifier.py; these tests pin the fix so it can't silently
regress.
"""

from classifier import _filename_has_keyword, classify_file


def test_plural_filenames_match():
    assert _filename_has_keyword("agreement track changes.docx", "track change")
    assert _filename_has_keyword("nda redlines.docx", "redline")
    assert _filename_has_keyword("nda with comments.docx", "comment")
    assert _filename_has_keyword("draft markups.docx", "markup")


def test_singular_filenames_still_match():
    assert _filename_has_keyword("agreement track change.docx", "track change")
    assert _filename_has_keyword("nda redline.docx", "redline")
    assert _filename_has_keyword("nda with comment.docx", "comment")


def test_draftsman_false_positive_still_guarded():
    # The whole reason _filename_has_keyword wraps keywords in \b...\b —
    # a bare substring match on "draft" would wrongly fire on "draftsman".
    assert not _filename_has_keyword("draftsman services agreement.docx", "draft")
    assert _filename_has_keyword("nda draft.docx", "draft")


def test_negotiat_stem_words_match():
    assert _filename_has_keyword("nda negotiated draft.docx", "negotiated")
    assert _filename_has_keyword("under negotiation.docx", "negotiation")
    assert _filename_has_keyword("negotiations ongoing.docx", "negotiation")  # plural via s?
    assert _filename_has_keyword("still negotiating v2.docx", "negotiating")


def test_classify_file_plural_and_singular_score_identically():
    plural = classify_file({"FileName": "Master Agreement - Track Changes.docx", "FileType": ".docx"})
    singular = classify_file({"FileName": "Master Agreement - Track Change.docx", "FileType": ".docx"})
    assert plural["category"] == singular["category"] == "Draft/Negotiation Copy"
    assert plural["score"] == singular["score"] == 4
