from document_sequence import (
    ROLE_FINAL,
    ROLE_FIRST_REDLINE,
    ROLE_INTERMEDIATE_REDLINE,
    ROLE_ORIGINAL,
    sequence_documents,
)

# Two texts that ARE the same contract at different stages (high similarity),
# and one that is a genuinely different agreement (low similarity).
NDA_TEXT = (
    "MUTUAL NONDISCLOSURE AGREEMENT This Agreement is entered into between the parties "
    "for the purpose of evaluating a potential business relationship. Confidential "
    "Information means any non-public information disclosed by either party. The "
    "receiving party shall protect such information for a period of three years. "
    "Neither party shall be obligated to enter into any further agreement. This "
    "Agreement is governed by the laws of the State of Illinois. "
) * 3
NDA_TEXT_EDITED = NDA_TEXT.replace("three years", "five years")
UNRELATED_TEXT = (
    "PURCHASE ORDER FORM Vendor shall deliver the equipment described in Exhibit A "
    "no later than the delivery date specified. Payment terms are net thirty days "
    "following receipt of a conforming invoice. Freight charges are prepaid and "
    "added to the invoice. Warranty claims must be submitted within ninety days. "
) * 3


def _f(file_id, name, text, *, entry=None, tc=False, tc_count=0, tc_first=None, authors=None):
    return {
        "ID": file_id,
        "FileName": name,
        "TextExtract": text,
        "EntryDate": entry,
        "has_tracked_changes": tc,
        "tracked_change_count": tc_count,
        "tracked_change_first_date": tc_first,
        "tracked_change_authors": authors,
    }


def test_original_then_redline_gets_high_confidence():
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        _f(2, "NDA marmon redline.docx", NDA_TEXT_EDITED, entry="2026-01-15",
           tc=True, tc_count=12, tc_first="2026-01-14", authors={"Wilk, Michele": 12}),
    ]
    result = sequence_documents(files)
    assert result["has_redline_evidence"] is True
    assert result["roles"][1]["role"] == ROLE_ORIGINAL
    assert result["roles"][2]["role"] == ROLE_FIRST_REDLINE
    assert result["request_confidence"] == "high"
    assert "Wilk, Michele" in result["roles"][2]["reasoning"]


def test_multiple_redline_rounds_ordered_by_edit_date():
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        # Uploaded out of order on purpose: upload dates disagree with edit
        # dates, and edit dates must win (Jeff's edit-history point).
        _f(3, "NDA round 2.docx", NDA_TEXT_EDITED, entry="2026-01-12",
           tc=True, tc_count=5, tc_first="2026-02-01"),
        _f(2, "NDA round 1.docx", NDA_TEXT_EDITED, entry="2026-01-20",
           tc=True, tc_count=9, tc_first="2026-01-14"),
    ]
    result = sequence_documents(files)
    assert result["roles"][2]["role"] == ROLE_FIRST_REDLINE
    assert result["roles"][3]["role"] == ROLE_INTERMEDIATE_REDLINE
    assert [f["ID"] for f in result["ordered"]] == [1, 2, 3]


def test_executed_filename_becomes_final():
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        _f(2, "NDA redline.docx", NDA_TEXT_EDITED, entry="2026-01-15",
           tc=True, tc_count=7, tc_first="2026-01-14"),
        _f(3, "NDA - fully executed.pdf", NDA_TEXT_EDITED, entry="2026-02-01"),
    ]
    result = sequence_documents(files)
    assert result["roles"][3]["role"] == ROLE_FINAL
    assert result["roles"][1]["role"] == ROLE_ORIGINAL
    assert result["roles"][2]["role"] == ROLE_FIRST_REDLINE


def test_unrelated_documents_drop_confidence_to_low():
    # The mispairing trap: an NDA and an unrelated purchase order in one
    # request must not be presented as trustworthy negotiation rounds.
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        _f(2, "Order form.docx", UNRELATED_TEXT, entry="2026-01-15",
           tc=True, tc_count=4, tc_first="2026-01-14"),
    ]
    result = sequence_documents(files)
    assert result["request_confidence"] == "low"
    assert any("distinct agreements" in n for n in result["notes"])
    assert all(r["confidence"] == "low" for r in result["roles"].values())


def test_no_redline_evidence_is_medium_not_high():
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        _f(2, "NDA final.docx", NDA_TEXT_EDITED, entry="2026-02-01"),
    ]
    result = sequence_documents(files)
    assert result["has_redline_evidence"] is False
    assert result["request_confidence"] == "medium"


def test_clean_document_after_redline_is_low_confidence_intermediate():
    files = [
        _f(1, "NDA redline.docx", NDA_TEXT, entry="2026-01-10",
           tc=True, tc_count=6, tc_first="2026-01-09"),
        _f(2, "NDA clean copy.docx", NDA_TEXT_EDITED, entry="2026-01-20"),
    ]
    result = sequence_documents(files)
    assert result["roles"][1]["role"] == ROLE_FIRST_REDLINE
    assert result["roles"][2]["role"] == ROLE_INTERMEDIATE_REDLINE
    assert result["roles"][2]["confidence"] == "low"


def test_tracked_changes_file_usable_even_with_thin_text():
    # A redline docx whose TextExtract is empty (CobbleStone's extraction rot)
    # must still sequence — its markup is the evidence, and real text comes
    # from the base/proposed renderings.
    files = [_f(1, "NDA redline.docx", "", entry="2026-01-10",
                tc=True, tc_count=11, tc_first="2026-01-09")]
    result = sequence_documents(files)
    assert result["roles"][1]["role"] == ROLE_FIRST_REDLINE
    assert result["has_redline_evidence"] is True


def test_no_usable_files_returns_empty_not_error():
    result = sequence_documents([_f(1, "tiny.docx", "too short")])
    assert result["roles"] == {}
    assert result["request_confidence"] == "low"
    assert result["notes"] == ["no usable files"]


def test_empty_file_list():
    result = sequence_documents([])
    assert result["roles"] == {}
    assert result["has_redline_evidence"] is False


def test_base_text_preferred_for_similarity_when_present():
    # When a caller supplies base_text (from docx_redline), cohesion should be
    # judged on it rather than a rotted TextExtract.
    files = [
        _f(1, "NDA draft.docx", NDA_TEXT, entry="2026-01-10"),
        dict(_f(2, "NDA redline.docx", "", entry="2026-01-15",
                tc=True, tc_count=8, tc_first="2026-01-14"), base_text=NDA_TEXT_EDITED),
    ]
    result = sequence_documents(files)
    assert result["request_confidence"] == "high"
    assert result["notes"] == []
