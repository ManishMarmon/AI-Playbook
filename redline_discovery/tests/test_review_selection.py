"""
Coverage for select_playbook()'s refuse-on-ambiguity design: it must return
None (never guess) on zero or 2+ manifest matches, and only resolve when
exactly one manifest entry claims the given business sector.
"""

from review_selection import select_playbook


MANIFEST = [
    {"id": "freo-group-au", "businessSectors": ["Wind", "Mining"]},
    {"id": "nda-usa", "businessSectors": []},
    {"id": "duplicate-a", "businessSectors": ["Aerospace"]},
    {"id": "duplicate-b", "businessSectors": ["Aerospace"]},
]


def test_no_business_sector_given():
    result = select_playbook(None, MANIFEST)
    assert result == {"playbook_id": None, "reason": "no_business_sector"}


def test_no_matching_playbook():
    result = select_playbook("Healthcare", MANIFEST)
    assert result == {"playbook_id": None, "reason": "no_matching_playbook"}


def test_ambiguous_match_refuses_to_guess():
    result = select_playbook("Aerospace", MANIFEST)
    assert result["playbook_id"] is None
    assert result["reason"] == "ambiguous_playbook_match"


def test_exactly_one_match_resolves():
    result = select_playbook("Wind", MANIFEST)
    assert result == {"playbook_id": "freo-group-au", "reason": None}
