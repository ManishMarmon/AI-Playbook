"""
The export must reproduce the tagger's own aggregation exactly — if the two
disagree about what counts as confirmed, a resumed run silently reports
different numbers from an uninterrupted one.
"""

from export_clause_findings import build_payload


def _row(rid, confirmed=0, flagged=0, low=0, verify_failed=0, failed=False):
    verified = (
        [{"clause_name": f"c{i}", "verification": {"accurate": True}} for i in range(confirmed)]
        + [{"clause_name": f"f{i}", "verification": {"accurate": False, "issue": "x"}}
           for i in range(flagged)]
    )
    return {
        "request_id": rid,
        "tagging_failed": failed,
        "verified_findings": [] if failed else verified,
        "low_or_noise_findings": [{"clause_name": f"l{i}"} for i in range(low)],
        "verification_failed_count": verify_failed,
        "model": "gpt-5.6-luna",
        "chunk_signature": "abc",
    }


def test_confirmed_and_flagged_split_on_the_verification_verdict():
    rows = {1: _row(1, confirmed=3, flagged=2)}
    r = build_payload(rows)["result"]
    assert len(r["confirmed"]) == 3
    assert len(r["flagged"]) == 2


def test_failed_requests_contribute_nothing_but_are_named():
    rows = {1: _row(1, confirmed=2), 2: _row(2, failed=True)}
    r = build_payload(rows)["result"]
    assert len(r["confirmed"]) == 2
    assert r["requestsProcessed"] == 1
    assert r["requestsFailed"] == 1
    assert r["failedRequestIds"] == [2]


def test_low_noise_and_verify_failures_are_summed_across_requests():
    rows = {1: _row(1, low=3, verify_failed=1), 2: _row(2, low=4, verify_failed=2)}
    r = build_payload(rows)["result"]
    assert r["lowOrNoiseCount"] == 7
    assert r["verificationFailedCount"] == 3


def test_a_finding_with_no_verification_is_not_counted_as_confirmed():
    # Absence of a verdict is not a pass. Counting it as confirmed would let an
    # unchecked finding into the playbook as if it had survived the check.
    rows = {1: {"request_id": 1, "tagging_failed": False,
                "verified_findings": [{"clause_name": "c"}],
                "low_or_noise_findings": [], "verification_failed_count": 0}}
    r = build_payload(rows)["result"]
    assert r["confirmed"] == []
    assert len(r["flagged"]) == 1


def test_total_defaults_to_what_is_stored():
    r = build_payload({1: _row(1), 2: _row(2)})["result"]
    assert r["requestsTotal"] == 2


def test_expected_total_makes_a_partial_export_report_itself_as_partial():
    # Claiming 100/100 from 47 stored rows would make a partial export look
    # complete to every downstream reader, including Monique's methodology page.
    r = build_payload({i: _row(i) for i in range(47)}, expected_total=100)["result"]
    assert r["requestsProcessed"] == 47
    assert r["requestsTotal"] == 100


def test_export_is_flagged_as_db_derived():
    r = build_payload({1: _row(1)})["result"]
    assert r["exportedFromDb"] is True


def test_failed_ids_are_sorted_for_stable_output():
    rows = {9: _row(9, failed=True), 3: _row(3, failed=True), 5: _row(5, confirmed=1)}
    assert build_payload(rows)["result"]["failedRequestIds"] == [3, 9]


def test_shape_matches_what_the_downstream_chain_reads():
    # annotate_finding_sides.py and extract_confirmed_findings.py both key off
    # these names; a rename here breaks them silently.
    r = build_payload({1: _row(1, confirmed=1)})["result"]
    for key in ("confirmed", "flagged", "lowOrNoiseCount", "requestsProcessed",
                "requestsTotal", "requestsFailed", "failedRequestIds",
                "verificationFailedCount"):
        assert key in r, f"{key} missing — downstream scripts read it"
