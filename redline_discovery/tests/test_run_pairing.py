"""
Regression test for the destructive-rmtree fix: run_pairing.py's output
paths must be namespaced per (request_type, geography) population so two
different contract-type/jurisdiction runs never share (and therefore never
clobber) the same diff_chunks directory or summary files. This is what
protects against the exact near-miss that happened by hand with Equipment
Leasing's in-flight diff_chunks before this fix existed.
"""

from run_pairing import _population_tag


def test_no_filters_falls_back_to_all():
    assert _population_tag(None, None) == "all"


def test_different_populations_get_different_tags():
    tag_a = _population_tag("Equipment Leasing", "U.S.")
    tag_b = _population_tag("NDA", "U.S.")
    tag_c = _population_tag("Real Estate", "U.S.")
    assert len({tag_a, tag_b, tag_c}) == 3


def test_tag_is_filesystem_safe():
    tag = _population_tag("Equipment Leasing", "U.S.")
    assert " " not in tag
    assert "." not in tag
    assert tag == tag.lower()


def test_same_population_is_deterministic():
    assert _population_tag("NDA", "U.S.") == _population_tag("NDA", "U.S.")
