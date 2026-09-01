import provenance as P


def test_preference_order_puts_preferred_position_first():
    assert P.strongest([P.INITIAL_VS_FINAL, P.INITIAL_VS_FIRST_REDLINE]) == P.INITIAL_VS_FIRST_REDLINE
    assert P.strongest([P.SINGLE_DOC_BASELINE, P.REDLINE_INTERNAL]) == P.REDLINE_INTERNAL
    assert P.strongest([P.STANDALONE_CONTENT, P.INITIAL_VS_FINAL]) == P.INITIAL_VS_FINAL


def test_strongest_ignores_unknown_values_instead_of_raising():
    assert P.strongest(["something_new", P.INITIAL_VS_FINAL]) == P.INITIAL_VS_FINAL
    assert P.strongest(["only_unknown"]) is None
    assert P.strongest([]) is None


def test_is_preferred_position():
    assert P.is_preferred_position(P.INITIAL_VS_FIRST_REDLINE)
    assert P.is_preferred_position(P.REDLINE_INTERNAL)
    assert not P.is_preferred_position(P.INITIAL_VS_FINAL)
    assert not P.is_preferred_position(P.SINGLE_DOC_BASELINE)
    assert not P.is_preferred_position(None)


def test_every_basis_has_a_label_and_description():
    for basis in P.PREFERENCE_ORDER:
        assert P.label(basis) != "Unspecified basis"
        assert P.describe(basis) != "The comparison basis for this rule was not recorded."


def test_label_and_describe_degrade_gracefully():
    assert P.label(None) == "Unspecified basis"
    assert P.label("bogus") == "Unspecified basis"
    assert "not recorded" in P.describe(None)


def test_rollup_all_preferred_position():
    r = P.rollup([P.INITIAL_VS_FIRST_REDLINE] * 3 + [P.REDLINE_INTERNAL] * 2)
    assert r["total"] == 5
    assert r["preferred_position_count"] == 5
    assert r["dominant"] == P.INITIAL_VS_FIRST_REDLINE
    assert r["summary"] == "Preferred position — all 5 evidence items"


def test_rollup_mixed_reports_the_split():
    r = P.rollup([P.INITIAL_VS_FIRST_REDLINE] * 14 + [P.INITIAL_VS_FINAL] * 3 + [P.SINGLE_DOC_BASELINE])
    assert r["total"] == 18
    assert r["preferred_position_count"] == 14
    assert r["summary"] == "Mixed — 14 of 18 evidence items are a pre-compromise Marmon position"


def test_rollup_no_preferred_position_labels_the_dominant_basis():
    r = P.rollup([P.INITIAL_VS_FINAL] * 4)
    assert r["preferred_position_count"] == 0
    assert r["summary"] == "Agreed outcome — 4 evidence items"
    assert r["dominant"] == P.INITIAL_VS_FINAL


def test_rollup_singular_grammar():
    assert P.rollup([P.INITIAL_VS_FINAL])["summary"] == "Agreed outcome — 1 evidence item"
    assert P.rollup([P.REDLINE_INTERNAL])["summary"] == "Preferred position — all 1 evidence item"


def test_rollup_empty():
    r = P.rollup([])
    assert r["total"] == 0
    assert r["dominant"] is None
    assert r["summary"] == "No comparison basis recorded"


def test_rollup_counts_are_exact():
    r = P.rollup([P.REDLINE_INTERNAL, P.REDLINE_INTERNAL, P.INITIAL_VS_FINAL])
    assert r["counts"] == {P.REDLINE_INTERNAL: 2, P.INITIAL_VS_FINAL: 1}


def test_labels_group_both_preferred_bases_under_one_reader_facing_name():
    # An attorney should not have to care whether a preferred position came
    # from two files or one file's markup — both read as "Preferred position".
    assert P.label(P.INITIAL_VS_FIRST_REDLINE) == P.label(P.REDLINE_INTERNAL) == "Preferred position"


# ── position side (whose edits) — separate dimension from the comparison ──

def test_position_label_distinguishes_whose_redline_it_is():
    assert P.position_label(P.REDLINE_INTERNAL, P.SIDE_MARMON) == "Marmon preferred position"
    assert P.position_label(P.REDLINE_INTERNAL, P.SIDE_COUNTERPARTY) == "Counterparty position"
    assert P.position_label(P.REDLINE_INTERNAL, P.SIDE_UNKNOWN) == "Redline position (side unconfirmed)"


def test_position_label_defaults_unconfirmed_rather_than_assuming_marmon():
    # The live failure this guards: a redline basis alone does not make the
    # edits ours (request 20597 was the counterparty's "LP REDLINE").
    assert P.position_label(P.REDLINE_INTERNAL, None) == "Redline position (side unconfirmed)"


def test_position_label_ignores_side_where_it_is_meaningless():
    # An agreed outcome blends both sides by definition; a baseline has no edits.
    assert P.position_label(P.INITIAL_VS_FINAL, P.SIDE_MARMON) == "Agreed outcome"
    assert P.position_label(P.SINGLE_DOC_BASELINE, P.SIDE_COUNTERPARTY) == "Accepted baseline"


def test_is_marmon_preferred_position_is_strict():
    assert P.is_marmon_preferred_position(P.REDLINE_INTERNAL, P.SIDE_MARMON)
    assert not P.is_marmon_preferred_position(P.REDLINE_INTERNAL, P.SIDE_UNKNOWN)
    assert not P.is_marmon_preferred_position(P.REDLINE_INTERNAL, P.SIDE_COUNTERPARTY)
    assert not P.is_marmon_preferred_position(P.INITIAL_VS_FINAL, P.SIDE_MARMON)


def test_dominant_side_unanimous_evidence():
    assert P.dominant_side([P.SIDE_MARMON, P.SIDE_MARMON]) == P.SIDE_MARMON
    assert P.dominant_side([P.SIDE_COUNTERPARTY]) == P.SIDE_COUNTERPARTY
    assert P.dominant_side([]) == P.SIDE_UNKNOWN
    assert P.dominant_side([None, P.SIDE_UNKNOWN]) == P.SIDE_UNKNOWN


def test_dominant_side_narrow_margin_reads_unconfirmed():
    # The original caution, kept: at these ratios the attribution really is a
    # coin flip and a rule must not be sold as ours.
    assert P.dominant_side([P.SIDE_MARMON, P.SIDE_MARMON, P.SIDE_COUNTERPARTY]) == P.SIDE_UNKNOWN
    assert P.dominant_side([P.SIDE_MARMON] * 5 + [P.SIDE_COUNTERPARTY] * 3) == P.SIDE_UNKNOWN
    assert P.dominant_side([P.SIDE_MARMON, P.SIDE_COUNTERPARTY]) == P.SIDE_UNKNOWN


def test_dominant_side_overwhelming_evidence_is_not_erased_by_a_handful():
    # The population-scale bug this replaced: MNDA-DEF-01's real counts were
    # 1,500 Marmon vs 12 counterparty (0.8%) and it read "unconfirmed", as did
    # 14 of 15 rules. Set membership cannot tell 1,500-vs-12 from 2-vs-1.
    assert P.dominant_side([P.SIDE_MARMON] * 1500 + [P.SIDE_COUNTERPARTY] * 12) == P.SIDE_MARMON
    assert P.dominant_side([P.SIDE_COUNTERPARTY] * 1500 + [P.SIDE_MARMON] * 12) == P.SIDE_COUNTERPARTY


def test_dominant_side_threshold_boundary():
    assert P.dominant_side([P.SIDE_MARMON] * 9 + [P.SIDE_COUNTERPARTY]) == P.SIDE_MARMON
    assert P.dominant_side([P.SIDE_MARMON] * 89 + [P.SIDE_COUNTERPARTY] * 11) == P.SIDE_UNKNOWN


def test_unattributed_edits_do_not_decide_whose_position_a_rule_is():
    # Word strips author names under some privacy settings. Those findings must
    # not dilute the denominator, or a rule with unanimous attributed evidence
    # would flip to unconfirmed just because many documents were anonymised.
    sides = [P.SIDE_MARMON] * 10 + [P.SIDE_UNKNOWN] * 500 + [None] * 100
    assert P.dominant_side(sides) == P.SIDE_MARMON


def test_dominant_side_is_symmetric_between_the_parties():
    # No thumb on the scale for Marmon: the same ratio must resolve the same way
    # whichever side holds it.
    for n, expected in ((12, P.SIDE_UNKNOWN), (2, P.SIDE_MARMON)):
        a = P.dominant_side([P.SIDE_MARMON] * 100 + [P.SIDE_COUNTERPARTY] * n)
        b = P.dominant_side([P.SIDE_COUNTERPARTY] * 100 + [P.SIDE_MARMON] * n)
        assert a == expected
        assert b == (P.SIDE_UNKNOWN if expected is P.SIDE_UNKNOWN else P.SIDE_COUNTERPARTY)


def test_position_describe_warns_against_adopting_counterparty_asks():
    text = P.position_describe(P.REDLINE_INTERNAL, P.SIDE_COUNTERPARTY)
    assert "not a Marmon position" in text
