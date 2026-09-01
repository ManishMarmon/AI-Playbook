"""
Covers the cap on how many findings reach a topic's drafting prompt.

The cap exists because the draft prompt embeds findings in full, so its size
grows with the topic's support: the largest topic in the 150-request run carried
158 findings, and the same topic covers ~65% of the population, so at 1,812
requests it reaches ~1,900 findings and a prompt too large to answer.

Two properties matter more than the cap itself:
  1. The sample must NOT change the evidence a rule claims. Counts, percentages
     and provenance are computed in Python from the complete list; only the
     model's view is capped.
  2. The sample must span requests, not repeat a few. A topic's findings arrive
     grouped by clause name, so a head slice can be dominated by a handful of
     contracts — and the prompt asks for the pattern ACROSS negotiations.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure_playbook_synthesis import draft_prompt, sample_for_draft  # noqa: E402


def findings(spec):
    """spec: {request_id: count} -> flat list, grouped by request the way
    by_clause_name assembly produces them."""
    out = []
    for rid, n in spec.items():
        out.extend({"request_id": rid, "clause_name": f"C{rid}", "n": i} for i in range(n))
    return out


def test_no_cap_returns_everything():
    fs = findings({1: 3, 2: 3})
    assert sample_for_draft(fs, 0) == (fs, False)
    assert sample_for_draft(fs, None) == (fs, False)


def test_under_the_cap_is_untouched():
    fs = findings({1: 3, 2: 3})
    shown, sampled = sample_for_draft(fs, 400)
    assert shown == fs and sampled is False


def test_cap_is_respected():
    shown, sampled = sample_for_draft(findings({i: 10 for i in range(100)}), 400)
    assert len(shown) == 400 and sampled is True


def test_sample_spans_every_request_before_repeating_one():
    # The property a head slice would violate: 5 requests x 100 findings, cap 5
    # must give one finding from each request, not 5 from the first.
    shown, _ = sample_for_draft(findings({i: 100 for i in range(5)}), 5)
    assert sorted(f["request_id"] for f in shown) == [0, 1, 2, 3, 4]


def test_a_head_slice_would_have_collapsed_to_one_request():
    # Stated as a test so the reason for round-robin is not lost: the input is
    # grouped by request, so [:5] is five findings from a single contract.
    fs = findings({i: 100 for i in range(5)})
    assert len({f["request_id"] for f in fs[:5]}) == 1
    shown, _ = sample_for_draft(fs, 5)
    assert len({f["request_id"] for f in shown}) == 5


def test_lopsided_support_does_not_starve_the_thin_requests():
    # One contract with 500 findings, nine with 1 each. All ten must appear.
    shown, _ = sample_for_draft(findings({0: 500, **{i: 1 for i in range(1, 10)}}), 20)
    assert {f["request_id"] for f in shown} >= set(range(10))


def test_it_stops_when_the_evidence_runs_out_rather_than_looping():
    fs = findings({1: 2, 2: 2})
    shown, sampled = sample_for_draft(fs, 400)
    assert len(shown) == 4 and sampled is False


def test_selection_is_deterministic():
    fs = findings({i: 7 for i in range(30)})
    a, _ = sample_for_draft(fs, 50)
    b, _ = sample_for_draft(fs, 50)
    assert [(f["request_id"], f["n"]) for f in a] == [(f["request_id"], f["n"]) for f in b]


def test_no_finding_is_shown_twice():
    shown, _ = sample_for_draft(findings({i: 10 for i in range(100)}), 400)
    assert len({(f["request_id"], f["n"]) for f in shown}) == len(shown)


def test_a_missing_request_id_does_not_crash_the_sort():
    fs = [{"request_id": None, "n": 0}] + findings({1: 5, 2: 5})
    shown, _ = sample_for_draft(fs, 4)
    assert len(shown) == 4


# --- the prompt must report the TRUE total, not the sample size -------------

TOPIC = {"topic_id": "T-1", "title": "Assignment", "category": "Transfer"}


def test_prompt_states_the_true_total_when_sampled():
    prompt = draft_prompt(TOPIC, findings({1: 1, 2: 1}), evidence_total=1900)
    assert "1900 total matching findings" in prompt
    assert "use the TOTAL of 1900 findings" in prompt


def test_prompt_says_all_when_nothing_was_dropped():
    fs = findings({1: 2, 2: 2})
    prompt = draft_prompt(TOPIC, fs, evidence_total=len(fs))
    assert "all 4 findings" in prompt
    assert "representative sample" not in prompt


def test_prompt_without_a_total_falls_back_to_what_it_was_given():
    # Keeps the old two-argument call site honest rather than reporting None.
    prompt = draft_prompt(TOPIC, findings({1: 3}))
    assert "all 3 findings" in prompt
