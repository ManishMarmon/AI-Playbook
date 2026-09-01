import provenance
from provenance_diff import build_request_diff

BASE = (
    "MUTUAL NONDISCLOSURE AGREEMENT The receiving party shall protect Confidential "
    "Information for a period of three years from disclosure. Neither party is obligated "
    "to enter any further agreement. This Agreement is governed by the laws of Delaware. "
) * 2
PROPOSED = BASE.replace("three years", "five years").replace("Delaware", "Illinois")
FINAL = BASE.replace("three years", "four years")

REQUEST = {"RequestID": 999, "RequestTitle": "NDA", "u_VendorCounterpartyName": "Acme",
           "u_Requestor": "someone", "u_RequestProcessStatus": "Contract Created",
           "nda_type": "Mutual"}


def _redline(fid=1, name="NDA marmon redline.docx", role="first_redline",
             base=BASE, proposed=PROPOSED, edits=None, authors=None, first_date="2026-01-05"):
    return {
        "id": fid, "file_name": name, "document_role": role, "sequence_confidence": "high",
        "has_tracked_changes": True, "redline_base_text": base, "redline_proposed_text": proposed,
        "tracked_change_edits": edits if edits is not None else [
            {"author": "Wilk, Michele", "date": "2026-01-05T10:00:00+00:00",
             "kind": "insertion", "text": "five years"},
            {"author": "Wilk, Michele", "date": "2026-01-05T10:02:00+00:00",
             "kind": "deletion", "text": "three years"},
            {"author": "Wilk, Michele", "date": "2026-01-05T10:03:00+00:00",
             "kind": "insertion", "text": "Illinois"},
        ],
        "tracked_change_authors": authors if authors is not None else {"Wilk, Michele": 3},
        "tracked_change_first_date": first_date,
        "text": proposed,
    }


def _clean(fid, name, role, text):
    return {"id": fid, "file_name": name, "document_role": role, "sequence_confidence": "medium",
            "has_tracked_changes": False, "redline_base_text": None, "redline_proposed_text": None,
            "tracked_change_edits": None, "tracked_change_authors": None,
            "tracked_change_first_date": None, "text": text}


def test_redline_gives_preferred_position_basis():
    rec = build_request_diff([_redline()], REQUEST)
    assert rec["comparison_basis"] == provenance.REDLINE_INTERNAL
    assert rec["comparison_basis_label"] == "Preferred position"
    assert provenance.is_preferred_position(rec["comparison_basis"])
    assert rec["edits"], "should produce edits from base-vs-proposed"
    assert rec["source_files"] == [{"file_id": 1, "file_name": "NDA marmon redline.docx",
                                     "role": "first_redline"}]
    assert rec["edit_authors"] == {"Wilk, Michele": 3}
    assert rec["sequence_confidence"] == "high"


def test_redline_edits_capture_the_actual_change():
    # The diff is word-level and reports the MINIMAL change, so the term edit
    # shows up as "three" -> "five" (the unchanged word "years" is not part of
    # the edit) — assert on the words that actually changed.
    rec = build_request_diff([_redline()], REQUEST)
    blob = " ".join(e["before"] + " " + e["after"] for e in rec["edits"])
    assert "three" in blob and "five" in blob
    assert "Delaware" in blob and "Illinois" in blob
    # context must be carried so the tagger can locate the clause
    assert any(e.get("context_before") or e.get("context_after") for e in rec["edits"])


def test_per_edit_author_attribution():
    rec = build_request_diff([_redline()], REQUEST)
    attributed = [e for e in rec["edits"] if e["authors"] != ["unattributed"]]
    assert attributed, "at least one edit should be attributed to the tracked-change author"
    assert "Wilk, Michele" in attributed[0]["authors"]
    assert "edit_dates" in attributed[0]


def test_unmatched_edit_is_unattributed_not_guessed():
    # Tracked-change list deliberately does not mention the changed text, so
    # attribution must abstain rather than assign the only known author.
    rl = _redline(edits=[{"author": "Someone Else", "date": None, "kind": "insertion",
                          "text": "a totally unrelated phrase"}])
    rec = build_request_diff([rl], REQUEST)
    assert all(e["authors"] == ["unattributed"] for e in rec["edits"])


def test_falls_back_to_initial_vs_final_when_no_redline_markup():
    files = [_clean(1, "NDA draft.docx", "original", BASE),
             _clean(2, "NDA - fully executed.pdf", "final", FINAL)]
    rec = build_request_diff(files, REQUEST)
    assert rec["comparison_basis"] == provenance.INITIAL_VS_FINAL
    assert rec["comparison_basis_label"] == "Agreed outcome"
    assert not provenance.is_preferred_position(rec["comparison_basis"])
    assert rec["edits"]
    assert {sf["role"] for sf in rec["source_files"]} == {"original", "final"}
    assert any("agreed outcome" in n for n in rec["notes"])
    # fallback edits must never claim authorship
    assert all(e["authors"] == ["unattributed"] for e in rec["edits"])


def test_redline_preferred_over_original_final_pair():
    # A request with BOTH a redline and an original/final pair must use the
    # redline: preferred position beats agreed outcome.
    files = [_clean(1, "NDA draft.docx", "original", BASE),
             _redline(fid=2), _clean(3, "NDA executed.pdf", "final", FINAL)]
    rec = build_request_diff(files, REQUEST)
    assert rec["comparison_basis"] == provenance.REDLINE_INTERNAL
    assert [sf["file_id"] for sf in rec["source_files"]] == [2]


def test_single_document_is_baseline_with_no_edits():
    rec = build_request_diff([_clean(1, "NDA signed.pdf", "final", FINAL)], REQUEST)
    assert rec["comparison_basis"] == provenance.SINGLE_DOC_BASELINE
    assert rec["edits"] == []
    assert rec["comparison_basis_label"] == "Accepted baseline"


def test_no_usable_documents_leaves_basis_unset():
    rec = build_request_diff([_clean(1, "tiny.docx", "original", "too short")], REQUEST)
    assert rec["comparison_basis"] is None
    assert rec["notes"] == ["no usable documents"]


def test_earliest_redline_chosen_when_role_missing():
    later = _redline(fid=5, role=None, first_date="2026-03-01")
    earlier = _redline(fid=4, role=None, first_date="2026-01-01")
    rec = build_request_diff([later, earlier], REQUEST)
    assert [sf["file_id"] for sf in rec["source_files"]] == [4]


def test_no_net_change_redline_is_reported_not_silently_empty():
    rl = _redline(base=BASE, proposed=BASE)
    rec = build_request_diff([rl], REQUEST)
    assert rec["edits"] == []
    assert any("no net text change" in n for n in rec["notes"])


def test_no_op_first_redline_falls_through_to_a_later_redline():
    # Live regression: requests 19841/19884/20522 each had a formatting-only
    # first redline plus an intermediate redline holding 46-79 real Marmon
    # tracked changes. Stopping at the no-op first redline threw the whole
    # request away as SINGLE_DOC_BASELINE with nothing to tag.
    noop = _redline(fid=1, name="Counterparty template.docx", role="first_redline",
                    base=BASE, proposed=BASE, first_date="2026-01-01")
    real = _redline(fid=2, name="Marmon Keystone NDA MK edits.docx",
                    role="intermediate_redline", first_date="2026-02-01")
    rec = build_request_diff([noop, real], REQUEST)
    assert rec["comparison_basis"] == provenance.REDLINE_INTERNAL
    assert [sf["file_id"] for sf in rec["source_files"]] == [2]
    assert rec["edits"], "the later redline's real edits must be used"
    # both the skip and the non-first round must be disclosed, not silent
    assert any("skipped" in n for n in rec["notes"])
    assert any("intermediate redline" in n for n in rec["notes"])


def test_first_redline_still_wins_when_it_has_real_edits():
    # The fall-through must not change the ordering: an earlier round with real
    # edits is closest to the opening ask and stays preferred.
    first = _redline(fid=1, role="first_redline", first_date="2026-01-01")
    later = _redline(fid=2, role="intermediate_redline", first_date="2026-02-01")
    rec = build_request_diff([later, first], REQUEST)
    assert [sf["file_id"] for sf in rec["source_files"]] == [1]
    assert not any("skipped" in n for n in rec["notes"])


def test_all_redlines_no_op_reports_every_skip():
    a = _redline(fid=1, role="first_redline", base=BASE, proposed=BASE)
    b = _redline(fid=2, role="intermediate_redline", base=BASE, proposed=BASE)
    rec = build_request_diff([a, b], REQUEST)
    assert rec["edits"] == []
    assert len([n for n in rec["notes"] if "no net text change" in n]) == 2
    assert rec["comparison_basis"] == provenance.SINGLE_DOC_BASELINE


def test_baseline_note_does_not_claim_one_document_when_there_are_several():
    # The old wording said "only one usable document" even for a request
    # holding three, which misreported the evidence to anyone reading the notes.
    a = _redline(fid=1, role="first_redline", base=BASE, proposed=BASE)
    b = _clean(2, "Other draft.docx", "intermediate_redline", FINAL)
    rec = build_request_diff([a, b], REQUEST)
    assert rec["comparison_basis"] == provenance.SINGLE_DOC_BASELINE
    baseline_note = next(n for n in rec["notes"] if "no comparison possible" in n)
    assert "2 usable documents" in baseline_note


def test_high_edit_cap_prevents_silent_truncation():
    # 60 distinct changes: the old 40-edit default would have dropped 20 real
    # negotiated edits; the redline cap must keep them.
    base_lines, proposed_lines = [], []
    for i in range(60):
        base_lines.append(f"Section {i}: the term shall be THREE years and notice is TEN days. ")
        proposed_lines.append(f"Section {i}: the term shall be FIVE years and notice is TEN days. ")
    rl = _redline(base="".join(base_lines), proposed="".join(proposed_lines), edits=[])
    rec = build_request_diff([rl], REQUEST)
    assert len(rec["edits"]) >= 60
    assert rec["edits_truncated"] is False


def test_nda_type_and_request_metadata_carried_through():
    rec = build_request_diff([_redline()], REQUEST)
    assert rec["request_id"] == 999
    assert rec["nda_type"] == "Mutual"
    assert rec["vendor"] == "Acme"
