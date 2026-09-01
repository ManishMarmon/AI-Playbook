"""
The methodology block is what tells a reviewing attorney how much weight the
rules deserve, so its numbers and caveats must describe THIS run — never
boilerplate. These tests mostly assert that a caveat appears only when the data
warrants it, and that its opposite appears when it doesn't.
"""

import methodology
import provenance

FUNNEL = {
    "scope": {"request_type": "NDA", "geography": "U.S.", "top": 100},
    "counts": {
        "total_requests": 3026,
        "with_docx": 2462,
        "scanned_requests": 2462,
        "with_tracked_changes_redline": 2219,
        "mutual_with_redline": 200,
        "unclassified_with_redline": 1989,
        "subset_size": 100,
    },
    "by_year": {"mutual_subset": {"2026": 100}},
}


def _diff(rid, basis=provenance.REDLINE_INTERNAL, notes=None, dates=None):
    edits = [{"before": "three", "after": "five", "edit_dates": dates}] if dates else []
    return {"request_id": rid, "comparison_basis": basis, "notes": notes or [], "edits": edits}


def _finding(side, accurate=True):
    return {"position_side": side, "verification": {"accurate": accurate}}


def _findings(confirmed=(), flagged=(), verify_failed=0, failed_ids=(), processed=100):
    return {"result": {
        "confirmed": list(confirmed), "flagged": list(flagged),
        "requestsProcessed": processed, "requestsTotal": 100,
        "verificationFailedCount": verify_failed,
        "failedRequestIds": list(failed_ids),
    }}


# ── Funnel and sample ────────────────────────────────────────────────────────

def test_funnel_is_reported_in_order_with_real_counts():
    m = methodology.build_methodology(
        funnel=FUNNEL, diff_records=[_diff(1)], findings=_findings())
    counts = [s["count"] for s in m["sample"]["funnel"]]
    assert counts == [3026, 2462, 2462, 2219, 200, 100]
    assert counts == sorted(counts, reverse=True), "a funnel must never widen"
    assert m["sample"]["subsetSize"] == 100


def test_absent_funnel_keys_are_skipped_not_zero_filled():
    # A zero would read as "none qualified", which is a different claim from
    # "this stage wasn't measured".
    funnel = {"counts": {"total_requests": 10, "subset_size": 5}}
    m = methodology.build_methodology(funnel=funnel, diff_records=[], findings=_findings())
    assert [s["count"] for s in m["sample"]["funnel"]] == [10, 5]


def test_date_range_comes_from_the_edits_actually_analysed():
    diffs = [_diff(1, dates=["2026-06-23T10:00:00+00:00", "2026-07-01T10:00:00+00:00"]),
             _diff(2, dates=["2026-08-28T10:00:00+00:00", "2026-08-28T12:00:00+00:00"])]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    assert m["sample"]["dateRange"] == "23 Jun 2026 - 28 Aug 2026"


def test_single_date_is_not_rendered_as_a_range():
    m = methodology.build_methodology(
        funnel=FUNNEL, diff_records=[_diff(1, dates=["2026-08-28T10:00:00+00:00"])],
        findings=_findings())
    assert m["sample"]["dateRange"] == "28 Aug 2026"


def test_no_dates_leaves_range_absent_rather_than_inventing_one():
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                       findings=_findings())
    assert m["sample"]["dateRange"] is None


# ── Caveats: present only when warranted ─────────────────────────────────────

def test_agreed_outcome_caveat_appears_when_a_fallback_basis_was_used():
    diffs = [_diff(1), _diff(2, basis=provenance.INITIAL_VS_FINAL)]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    text = " ".join(m["caveats"])
    assert "1 of 2 contracts had no usable redline markup" in text
    assert "agreed outcome" in text


def test_all_redline_run_states_that_positively_instead_of_the_caveat():
    # The regression this guards: printing Jeff's "intermediates were missing"
    # caveat on a run where every rule came from real markup would understate
    # the evidence.
    diffs = [_diff(1), _diff(2), _diff(3)]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    text = " ".join(m["caveats"])
    assert "Every one of the 3 contracts analysed had usable tracked-change markup" in text
    assert "had no usable redline markup" not in text


def test_classifier_coverage_caveat_states_the_unclassified_remainder():
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                       findings=_findings())
    text = " ".join(m["caveats"])
    assert "1,989 are not yet classified" in text
    assert "not the most recent of all mutual NDAs that exist" in text


def test_later_round_caveat_appears_only_when_a_later_round_was_used():
    with_note = _diff(1, notes=["edits come from the intermediate redline rather than a "
                                 "first redline, so they reflect..."])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[with_note, _diff(2)],
                                       findings=_findings())
    assert any("1 contract(s) the first redline contained only formatting" in c
               for c in m["caveats"])

    m2 = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                        findings=_findings())
    assert not any("only formatting" in c for c in m2["caveats"])


def test_unconfirmed_side_caveat_counts_findings_not_requests():
    findings = _findings(confirmed=[_finding("marmon"), _finding("unknown"),
                                     _finding("unknown")])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    assert any("2 finding(s) could not be attributed to one side" in c for c in m["caveats"])


def test_no_unconfirmed_sides_means_no_such_caveat():
    findings = _findings(confirmed=[_finding("marmon"), _finding("counterparty")])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    assert not any("could not be attributed" in c for c in m["caveats"])


def test_verification_and_tagging_gaps_are_disclosed():
    findings = _findings(confirmed=[_finding("marmon")], verify_failed=4, failed_ids=[123, 456])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    text = " ".join(m["caveats"])
    assert "4 finding(s) could not complete the second-pass accuracy check" in text
    assert "2 contract(s) failed the tagging step" in text and "123" in text


def test_clean_run_discloses_no_gaps():
    findings = _findings(confirmed=[_finding("marmon")])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    text = " ".join(m["caveats"])
    assert "accuracy check" not in text
    assert "failed the tagging step" not in text


# ── Tallies ──────────────────────────────────────────────────────────────────

def test_position_sides_use_the_same_wording_as_per_rule_labels():
    findings = _findings(confirmed=[_finding("marmon"), _finding("marmon"),
                                     _finding("counterparty")])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    assert m["positionSides"][0] == {"label": "Marmon preferred position", "count": 2}
    assert {"label": "Counterparty position", "count": 1} in m["positionSides"]
    # must match provenance.position_label's wording exactly, or a tally and a
    # rule chip would name the same thing differently
    assert m["positionSides"][0]["label"] == provenance.position_label(
        provenance.REDLINE_INTERNAL, provenance.SIDE_MARMON)


def test_flagged_findings_count_toward_side_tallies_and_are_reported():
    findings = _findings(confirmed=[_finding("marmon")],
                          flagged=[_finding("counterparty", accurate=False)])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    assert m["verification"]["confirmed"] == 1
    assert m["verification"]["flagged"] == 1
    assert sum(s["count"] for s in m["positionSides"]) == 2


def test_comparison_basis_tally_uses_reader_facing_labels():
    diffs = [_diff(1), _diff(2, basis=provenance.INITIAL_VS_FINAL)]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    labels = {b["label"] for b in m["comparisonBasis"]}
    assert provenance.label(provenance.REDLINE_INTERNAL) in labels
    assert provenance.label(provenance.INITIAL_VS_FINAL) in labels


def test_tallies_are_deterministic_across_runs():
    findings = _findings(confirmed=[_finding("marmon"), _finding("counterparty")])
    a = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    b = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)], findings=findings)
    assert a == b, "the generated document must be byte-stable across runs"


def test_models_recorded_only_when_supplied():
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                       findings=_findings(), tag_model="gpt-5.6-luna")
    assert m["models"] == {"clauseTagging": "gpt-5.6-luna"}


# ── Date range must not be misrepresented by one outlier ─────────────────────

def test_edit_years_count_contracts_not_edits():
    diffs = [_diff(1, dates=["2026-06-23T10:00:00+00:00", "2026-07-01T10:00:00+00:00"]),
             _diff(2, dates=["2026-08-01T10:00:00+00:00"]),
             _diff(3, dates=["2025-03-27T10:00:00+00:00"])]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    assert m["sample"]["editYears"] == [{"label": "2026", "count": 2},
                                        {"label": "2025", "count": 1}]


def test_outlier_year_widens_the_range_but_the_spread_still_shows_concentration():
    # Live case (#20095): one 2026 contract carries a March-2025 redline, which
    # stretched the stated span to 17 months while 98 of 99 contracts sat in
    # 2026. Both facts must be available, so the range alone can't mislead.
    diffs = [_diff(i, dates=[f"2026-07-{i:02d}T10:00:00+00:00"]) for i in range(1, 10)]
    diffs.append(_diff(99, dates=["2025-03-27T10:00:00+00:00"]))
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    assert m["sample"]["dateRange"] == "27 Mar 2025 - 9 Jul 2026"
    assert m["sample"]["editYears"][0] == {"label": "2026", "count": 9}


def test_single_year_sample_reports_one_year_bucket():
    diffs = [_diff(1, dates=["2026-06-23T10:00:00+00:00"]),
             _diff(2, dates=["2026-08-28T10:00:00+00:00"])]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    assert m["sample"]["editYears"] == [{"label": "2026", "count": 2}]


def test_undated_requests_are_excluded_from_the_year_spread():
    diffs = [_diff(1, dates=["2026-06-23T10:00:00+00:00"]), _diff(2)]
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=_findings())
    assert m["sample"]["editYears"] == [{"label": "2026", "count": 1}]


def test_passing_the_flat_confirmed_array_fails_loudly():
    # The two --findings flags in this pipeline take different shapes. Given the
    # array, this must say so rather than raise an opaque AttributeError or, worse,
    # silently report zero flagged findings.
    import pytest
    with pytest.raises(TypeError, match="full payload"):
        methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                       findings=[{"position_side": "marmon"}])


def test_contracts_that_yielded_nothing_significant_are_disclosed():
    # "100 contracts analysed" reads as 100 contracts' worth of evidence. Live:
    # 2 of 100 (both the same Fluor template) produced only low-significance
    # edits, so the rules actually rest on 98.
    diffs = [_diff(1, dates=["2026-07-01T00:00:00+00:00"]),
             _diff(2, dates=["2026-07-02T00:00:00+00:00"]),
             _diff(3, dates=["2026-07-03T00:00:00+00:00"])]
    findings = _findings(confirmed=[{**_finding("marmon"), "request_id": 1},
                                     {**_finding("marmon"), "request_id": 2}])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=findings)
    text = " ".join(m["caveats"])
    assert "1 of the 3 contracts analysed produced no finding" in text
    assert "rest on 2 contracts' evidence" in text
    assert "requests 3" in text


def test_no_such_caveat_when_every_contract_contributed():
    diffs = [_diff(1, dates=["2026-07-01T00:00:00+00:00"]),
             _diff(2, dates=["2026-07-02T00:00:00+00:00"])]
    findings = _findings(confirmed=[{**_finding("marmon"), "request_id": 1},
                                     {**_finding("marmon"), "request_id": 2}])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=findings)
    assert not any("produced no finding" in c for c in m["caveats"])


def test_contracts_with_no_edits_are_not_counted_as_silent():
    # A contract with zero edits was never a source of evidence in the first
    # place; blaming it for contributing nothing would misstate the sample.
    diffs = [_diff(1, dates=["2026-07-01T00:00:00+00:00"]), _diff(2)]
    findings = _findings(confirmed=[{**_finding("marmon"), "request_id": 1}])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=findings)
    assert not any("produced no finding" in c for c in m["caveats"])


def test_many_silent_contracts_omit_the_id_list():
    diffs = [_diff(i, dates=["2026-07-01T00:00:00+00:00"]) for i in range(1, 12)]
    findings = _findings(confirmed=[{**_finding("marmon"), "request_id": 1}])
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=diffs, findings=findings)
    caveat = next(c for c in m["caveats"] if "produced no finding" in c)
    assert "10 of the 11 contracts" in caveat
    assert "requests" not in caveat, "an 10-id list would bloat the page"


def test_complete_coverage_states_it_positively_instead_of_hedging():
    # The scope expanded from a 100-contract sample to the whole population.
    # Once nothing is unclassified, printing "the sample may be incomplete"
    # would understate the evidence; printing nothing would leave the reader
    # unsure coverage was ever checked.
    funnel = {"counts": {**FUNNEL["counts"], "unclassified_with_redline": 0,
                         "mutual_with_redline": 1930, "subset_size": 1930}}
    m = methodology.build_methodology(funnel=funnel, diff_records=[_diff(1)],
                                       findings=_findings())
    text = " ".join(m["caveats"])
    assert "complete population of US mutual NDAs" in text
    assert "not yet classified" not in text
    assert "not a sample of it" in text


def test_partial_coverage_still_hedges():
    m = methodology.build_methodology(funnel=FUNNEL, diff_records=[_diff(1)],
                                       findings=_findings())
    text = " ".join(m["caveats"])
    assert "1,989 are not yet classified" in text
    assert "complete population" not in text
