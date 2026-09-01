from author_attribution import (
    COUNTERPARTY,
    MARMON,
    UNKNOWN,
    build_marmon_roster,
    classify_author,
    group_authors_by_side,
    is_anonymous,
    name_tokens,
    normalize_name,
    summarize_sides,
)

REQUEST = {
    "u_HandlingAttorneyEmail": "michele.wilk@marmon.com",
    "u_VendorCounterpartyName": "Liberty Packaging LLC",
    "u_LawFirmName": "Eversheds Sutherland",
}


# ── name normalization: the live double-counting bug ───────────────────────

def test_surname_first_and_given_first_normalize_together():
    # "Wilk, Michele" (1,689 files) and "Michele Wilk" (256 files) are one
    # attorney — the exact case that would otherwise double-count the most
    # prolific editor in the dataset.
    assert normalize_name("Wilk, Michele") == normalize_name("Michele Wilk")
    assert normalize_name("WILK, MICHELE") == normalize_name("michele wilk")


def test_middle_initial_does_not_block_a_match():
    assert normalize_name("Conway, Tegan A") == normalize_name("Tegan Conway")


def test_site_code_suffix_stripped():
    assert normalize_name("Bergener, Karin (US-AVL2-CNTR)") == normalize_name("Karin Bergener")


def test_distinct_people_do_not_collapse():
    assert normalize_name("Michele Wilk") != normalize_name("Michael Wilkins")


def test_name_tokens_drops_single_letters():
    assert name_tokens("Tegan A Conway") == frozenset({"tegan", "conway"})


# ── anonymized authors must never become a person ─────────────────────────

def test_word_privacy_placeholders_are_anonymous():
    for value in ("Author", "author", "", "  ", "Unknown", "Windows User", "unattributed"):
        assert is_anonymous(value), value


def test_anonymous_author_is_unknown_side():
    assert classify_author("Author", REQUEST) == UNKNOWN
    assert classify_author("", REQUEST) == UNKNOWN
    assert classify_author(None, REQUEST) == UNKNOWN


# ── side classification ───────────────────────────────────────────────────

def test_handling_attorney_email_match_is_marmon():
    assert classify_author("Wilk, Michele", REQUEST) == MARMON
    assert classify_author("Michele Wilk", REQUEST) == MARMON


def test_surname_only_email_still_matches():
    request = {**REQUEST, "u_HandlingAttorneyEmail": "m.wilk@marmon.com"}
    assert classify_author("Wilk, Michele", request) == MARMON


def test_counterparty_company_name_match():
    assert classify_author("Liberty Packaging", REQUEST) == COUNTERPARTY


def test_law_firm_author_is_unknown_not_marmon():
    # u_LawFirmName can be either side's counsel, so a firm name appearing as
    # an edit author must NOT be assumed to be Marmon's — that would
    # manufacture a false preferred-position claim.
    assert classify_author("Eversheds Sutherland", REQUEST) == UNKNOWN


def test_unrecognized_person_is_unknown():
    assert classify_author("Alexander Ruiz", REQUEST) == UNKNOWN


def test_roster_recognizes_attorney_on_a_request_with_no_attorney_field():
    roster = build_marmon_roster([(REQUEST, ["Wilk, Michele"])])
    blank = {"u_HandlingAttorneyEmail": None, "u_VendorCounterpartyName": "Acme Inc"}
    assert classify_author("Michele Wilk", blank) == UNKNOWN
    assert classify_author("Michele Wilk", blank, roster) == MARMON


def test_roster_excludes_anonymous_and_non_matching_authors():
    roster = build_marmon_roster([(REQUEST, ["Author", "Someone Unrelated", "Wilk, Michele"])])
    assert normalize_name("Wilk, Michele") in roster
    assert normalize_name("Someone Unrelated") not in roster
    assert normalize_name("Author") not in roster


def test_roster_skips_requests_with_no_attorney_signal():
    roster = build_marmon_roster([({"u_HandlingAttorneyEmail": None}, ["Wilk, Michele"])])
    assert roster == frozenset()


# ── grouping + summary ────────────────────────────────────────────────────

def test_group_merges_aliases_so_one_person_counts_once():
    grouped = group_authors_by_side(["Wilk, Michele", "Michele Wilk"], REQUEST)
    assert len(grouped[MARMON]) == 1


def test_group_splits_sides():
    grouped = group_authors_by_side(
        ["Wilk, Michele", "Liberty Packaging", "Author"], REQUEST)
    assert grouped[MARMON] == ["Wilk, Michele"]
    assert grouped[COUNTERPARTY] == ["Liberty Packaging"]
    assert grouped[UNKNOWN] == ["Author"]


def test_summarize_sides_wording():
    assert summarize_sides({MARMON: ["a"], COUNTERPARTY: ["b"]}) == "both sides edited this clause"
    assert summarize_sides({MARMON: ["a"]}) == "Marmon-side edits only"
    assert summarize_sides({COUNTERPARTY: ["b"]}) == "counterparty edits only"
    assert summarize_sides({UNKNOWN: ["c"]}) == "editor's side could not be determined"
    assert summarize_sides({}) == "no recorded editors"


def test_empty_inputs_do_not_raise():
    assert group_authors_by_side(None, REQUEST)[MARMON] == []
    assert normalize_name(None) == ""
    assert build_marmon_roster([]) == frozenset()


# ── filename side signal (tie-breaker when authorship is unplaceable) ─────

from author_attribution import side_from_filename  # noqa: E402

LP_REQUEST = {"u_VendorCounterpartyName": "Liberty Packaging",
              "u_BusinessUnit": "Marmon Foodservice Technologies, Inc."}


def test_counterparty_initials_before_redline():
    # The live case: authorship said "Conway, Tegan A" (unplaceable), but the
    # filename says Liberty Packaging redlined it.
    assert side_from_filename(
        "Mutual Confidentiality Agreement - Liberty Packaging - LP REDLINE 2026.08.04.docx",
        LP_REQUEST) == COUNTERPARTY


def test_counterparty_full_name_in_filename():
    assert side_from_filename("JPE - Aero-Hose_NDA (Aero-Hose Redline 8.26.26).docx",
                              {"u_VendorCounterpartyName": "Aero-Hose LLC"}) == COUNTERPARTY


def test_marmon_redline_in_filename():
    assert side_from_filename("Marmon_-_Stream_NDA (marmon redline 8.28.26).docx",
                              {"u_VendorCounterpartyName": "Stream Inc"}) == MARMON


def test_filename_naming_both_parties_is_unknown():
    # Names both sides as editors — refuse to pick one.
    assert side_from_filename("Marmon Liberty Packaging redline.docx", LP_REQUEST) == UNKNOWN


def test_filename_without_a_markup_marker_is_unknown():
    # A plain document name says nothing about who edited it.
    assert side_from_filename("Liberty Packaging NDA.docx", LP_REQUEST) == UNKNOWN
    assert side_from_filename("ANDRITZ MNDA template_MAR2025 V9 (003).docx",
                              {"u_VendorCounterpartyName": "ANDRITZ"}) == UNKNOWN


def test_filename_signal_handles_empty_input():
    assert side_from_filename(None, LP_REQUEST) == UNKNOWN
    assert side_from_filename("", LP_REQUEST) == UNKNOWN
    assert side_from_filename("something redline.docx", {}) == UNKNOWN
