"""
Covers the clause-name normalisation and two-pass clustering added after the
population cluster call failed: 4,974 distinct names became a 916k-token prompt
and the service had no context left to answer in.

The invariant these tests protect is evidence integrity. Every finding's
clause_name must remain reachable from the topic it was filed under, because a
topic's evidence_requests/evidence_pct is what decides whether a rule reaches
the attorney-facing playbook or the suggested-rules sidecar. A name that gets
lost in translation between the display spelling the model saw and the raw
spelling on the findings silently understates a rule's support.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure_playbook_synthesis import (  # noqa: E402
    cluster_input, expand_to_raw_names, normalize_clause_name, prompt_rows)


def finding(name, **kw):
    base = {"clause_name": name, "request_id": kw.pop("request_id", 1),
            "significance": kw.pop("significance", "high"),
            "negotiation_intent": "x", "spirit_before": "a", "spirit_after": "b"}
    base.update(kw)
    return base


# --- normalisation ---------------------------------------------------------

def test_typography_variants_collapse():
    variants = ["Confidential Information - Exclusions",
                "Confidential Information – Exclusions",   # en dash
                "Confidential Information — Exclusions",   # em dash
                "Confidential Information / Exclusions",
                "Confidential Information (Exclusions)",
                "confidential information: exclusions",
                "Confidential   Information  Exclusions"]
    assert len({normalize_clause_name(v) for v in variants}) == 1


def test_genuinely_different_wording_stays_separate():
    # This is the judgement the cluster call exists to make; normalisation must
    # not pre-empt it, or two distinct issues merge with no way to notice.
    assert normalize_clause_name("Return of Documents") != \
        normalize_clause_name("Return or Destruction of Confidential Information")
    assert normalize_clause_name("Assignment") != normalize_clause_name("Subletting")


def test_apostrophes_and_accents_do_not_split_a_name():
    assert normalize_clause_name("Remedies; Attorneys' Fees") == \
        normalize_clause_name("Remedies — Attorneys’ Fees")


# --- cluster_input ---------------------------------------------------------

def test_counts_are_summed_across_spellings():
    rows = cluster_input([finding("Governing Law"), finding("governing law"),
                          finding("Governing  Law")])
    assert len(rows) == 1
    assert rows[0]["finding_count"] == 3
    assert rows[0]["raw_names"] == ["Governing  Law", "Governing Law", "governing law"]


def test_display_name_is_the_most_common_spelling():
    rows = cluster_input([finding("Governing Law"), finding("Governing Law"),
                          finding("governing law")])
    assert rows[0]["clause_name"] == "Governing Law"


def test_display_name_ties_break_alphabetically_for_reproducibility():
    # Same findings must always produce the same prompt, or two runs of the same
    # data are not comparable.
    a = cluster_input([finding("B Name"), finding("a name")])[0]["clause_name"]
    b = cluster_input([finding("a name"), finding("B Name")])[0]["clause_name"]
    assert a == b == "B Name"


def test_blank_names_are_dropped_not_grouped():
    rows = cluster_input([finding(""), finding("  "), finding("Assignment")])
    assert [r["clause_name"] for r in rows] == ["Assignment"]


def test_rows_are_ordered_by_support():
    rows = cluster_input([finding("Rare")] + [finding("Common")] * 4 + [finding("Mid")] * 2)
    assert [r["clause_name"] for r in rows] == ["Common", "Mid", "Rare"]


def test_examples_are_capped_and_truncated():
    long_text = "z" * 500
    rows = cluster_input([finding("X", negotiation_intent=long_text) for _ in range(10)])
    assert len(rows[0]["examples"]) == 3
    assert all(len(e["negotiation_intent"]) <= 220 for e in rows[0]["examples"])


def test_raw_names_is_withheld_from_the_prompt():
    rows = cluster_input([finding("Governing Law"), finding("governing law")])
    text = prompt_rows(rows)
    assert "raw_names" not in text
    assert "governing law" not in text          # only the display spelling is shown
    assert "Governing Law" in text


# --- expand_to_raw_names ---------------------------------------------------

def test_expansion_recovers_every_spelling():
    rows = cluster_input([finding("Governing Law"), finding("Governing Law"),
                          finding("governing law"), finding("Assignment")])
    topics = [{"topic_id": "T-1", "matching_clause_names": ["Governing Law", "Assignment"]}]
    expand_to_raw_names(topics, rows)
    assert set(topics[0]["matching_clause_names"]) == {
        "Governing Law", "governing law", "Assignment"}


def test_expansion_without_it_would_lose_findings():
    # The point of the expansion, stated as a test: findings are keyed on the raw
    # spelling, so a topic holding only the display name reaches a third of them.
    findings = [finding("Governing Law"), finding("governing law"),
                finding("GOVERNING LAW")]
    rows = cluster_input(findings)
    by_raw = {}
    for f in findings:
        by_raw.setdefault(f["clause_name"], []).append(f)

    unexpanded = [rows[0]["clause_name"]]
    assert sum(len(by_raw.get(n, [])) for n in unexpanded) == 1

    topics = [{"topic_id": "T-1", "matching_clause_names": list(unexpanded)}]
    expand_to_raw_names(topics, rows)
    assert sum(len(by_raw.get(n, []))
               for n in topics[0]["matching_clause_names"]) == 3


def test_expansion_is_idempotent():
    rows = cluster_input([finding("Governing Law"), finding("governing law")])
    topics = [{"topic_id": "T-1", "matching_clause_names": ["Governing Law"]}]
    expand_to_raw_names(topics, rows)
    first = list(topics[0]["matching_clause_names"])
    expand_to_raw_names(topics, rows)
    assert topics[0]["matching_clause_names"] == first


def test_expansion_tolerates_a_retyped_name():
    # The model is asked to echo names verbatim and mostly does. When it retypes
    # one with different punctuation, that must still find its group — otherwise
    # the whole group's findings drop out of the topic's evidence.
    rows = cluster_input([finding("Confidential Information - Exclusions"),
                          finding("Confidential Information / Exclusions")])
    topics = [{"topic_id": "T-1",
               "matching_clause_names": ["Confidential Information — Exclusions"]}]
    expand_to_raw_names(topics, rows)
    assert set(topics[0]["matching_clause_names"]) == {
        "Confidential Information - Exclusions", "Confidential Information / Exclusions"}


def test_expansion_keeps_an_unknown_name_rather_than_dropping_it():
    # A name the model invented should survive to dedupe/drafting, where it
    # matches no finding and costs nothing — silently deleting it here would
    # hide the hallucination instead of letting it show up as zero evidence.
    rows = cluster_input([finding("Assignment")])
    topics = [{"topic_id": "T-1", "matching_clause_names": ["Assignment", "Invented Topic"]}]
    expand_to_raw_names(topics, rows)
    assert "Invented Topic" in topics[0]["matching_clause_names"]


def test_expansion_does_not_duplicate_a_name_two_display_names_share():
    rows = cluster_input([finding("Governing Law"), finding("governing law")])
    topics = [{"topic_id": "T-1",
               "matching_clause_names": ["Governing Law", "Governing Law"]}]
    expand_to_raw_names(topics, rows)
    names = topics[0]["matching_clause_names"]
    assert len(names) == len(set(names))
