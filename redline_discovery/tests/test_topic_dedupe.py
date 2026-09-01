"""
A clause name claimed by two topics double-counts its findings into BOTH
topics' evidence_requests and evidence_pct — the numbers that decide whether a
rule reaches the main playbook or the suggested sidecar.

Measured on the live 1,043-finding run: 96 of 495 clause names were claimed
more than once, so the first delivered playbook overstated evidence. The prompt
asks the model for uniqueness; these tests cover the code that guarantees it.
"""

from azure_playbook_synthesis import dedupe_topic_claims


def _topic(tid, title, names):
    return {"topic_id": tid, "title": title, "category": "C", "category_prefix": "C",
            "matching_clause_names": list(names)}


def test_uncontested_topics_are_untouched():
    topics = [_topic("t1", "Assignment", ["Assignment"]),
              _topic("t2", "Term", ["Term and Termination"])]
    out, report = dedupe_topic_claims(topics, {"Assignment": 5, "Term and Termination": 3})
    assert report == []
    assert out[0]["matching_clause_names"] == ["Assignment"]
    assert out[1]["matching_clause_names"] == ["Term and Termination"]


def test_contested_name_ends_up_in_exactly_one_topic():
    topics = [_topic("t1", "Assignment", ["Assignment", "Successors"]),
              _topic("t2", "Transfer", ["Successors"])]
    counts = {"Assignment": 20, "Successors": 4}
    out, report = dedupe_topic_claims(topics, counts)
    all_claims = [n for t in out for n in t["matching_clause_names"]]
    assert all_claims.count("Successors") == 1
    assert len(report) == 1
    assert report[0]["clause_name"] == "Successors"


def test_name_goes_to_the_topic_with_more_independent_support():
    # t1 independently holds 20 findings; t2 holds 1. The contested name belongs
    # with the topic that is strongest on its own evidence, not one that would
    # only look strong by keeping contested names.
    topics = [_topic("t1", "Strong", ["Assignment", "Contested"]),
              _topic("t2", "Weak", ["Minor", "Contested"])]
    counts = {"Assignment": 20, "Minor": 1, "Contested": 6}
    out, report = dedupe_topic_claims(topics, counts)
    assert out[0]["matching_clause_names"] == ["Assignment", "Contested"]
    assert out[1]["matching_clause_names"] == ["Minor"]
    assert report[0]["assigned_to"] == "Strong"
    assert report[0]["removed_from"] == ["Weak"]


def test_three_way_contest_leaves_one_winner():
    topics = [_topic("t1", "A", ["a1", "x"]), _topic("t2", "B", ["b1", "b2", "x"]),
              _topic("t3", "C", ["x"])]
    counts = {"a1": 2, "b1": 5, "b2": 5, "x": 9}
    out, report = dedupe_topic_claims(topics, counts)
    holders = [t["title"] for t in out if "x" in t["matching_clause_names"]]
    assert holders == ["B"], "B has the most independent support (10)"
    assert set(report[0]["removed_from"]) == {"A", "C"}


def test_tie_is_broken_deterministically_by_topic_id():
    a = [_topic("t1", "A", ["shared"]), _topic("t2", "B", ["shared"])]
    b = [_topic("t2", "B", ["shared"]), _topic("t1", "A", ["shared"])]
    ra = dedupe_topic_claims(a, {"shared": 3})[1][0]["assigned_to"]
    rb = dedupe_topic_claims(b, {"shared": 3})[1][0]["assigned_to"]
    assert ra == rb, "same input set must give the same winner regardless of order"


def test_report_states_the_findings_at_stake():
    topics = [_topic("t1", "A", ["big", "shared"]), _topic("t2", "B", ["shared"])]
    _, report = dedupe_topic_claims(topics, {"big": 10, "shared": 7})
    assert report[0]["findings"] == 7, "the count is what would have been double-counted"


def test_every_name_survives_somewhere():
    # Dedupe must never drop a clause name entirely — that would silently
    # discard its findings instead of merely moving them.
    topics = [_topic("t1", "A", ["x", "y"]), _topic("t2", "B", ["y", "z"])]
    counts = {"x": 3, "y": 4, "z": 5}
    out, _ = dedupe_topic_claims(topics, counts)
    survived = {n for t in out for n in t["matching_clause_names"]}
    assert survived == {"x", "y", "z"}


def test_a_topic_can_be_left_with_nothing():
    # If every one of a topic's names belongs elsewhere, it ends up empty rather
    # than keeping borrowed evidence. Downstream then sees no matching findings
    # for it, which is the honest outcome.
    topics = [_topic("t1", "Real", ["a", "b"]), _topic("t2", "Duplicate", ["a", "b"])]
    out, report = dedupe_topic_claims(topics, {"a": 5, "b": 5})
    empties = [t["title"] for t in out if not t["matching_clause_names"]]
    assert empties == ["Duplicate"]
    assert len(report) == 2


def test_missing_counts_do_not_crash():
    topics = [_topic("t1", "A", ["known", "unknown"]), _topic("t2", "B", ["unknown"])]
    out, report = dedupe_topic_claims(topics, {"known": 4})
    assert len(report) == 1
    assert report[0]["findings"] == 0
