"""
Comparison-basis taxonomy — the single definition of "where did this rule
come from", used by the diffing, tagging, synthesis, and playbook-rendering
stages so one vocabulary runs end to end.

Jeff's requirement (2026-08-31): "the document-processing approach should
identify the source and comparison basis for each generated rule, such as
whether it came from a start-to-final differential or from the original
document to the first redline. This metadata would make it clear whether a
rule represented an agreed outcome or a preferred starting position."

The legal distinction that makes this necessary: a contract typically moves
through several rounds between Marmon (or a subsidiary) and the other side's
attorneys. Diffing the initial document against the FINAL one shows the
negotiated compromise — language both sides settled on, with the two
parties' edits mixed together and no way to tell who introduced what.
Diffing the initial document against the FIRST REDLINE shows what Marmon's
attorneys actually wanted before conceding anything. A playbook should
ideally teach the latter; where intermediate documents are missing it must
fall back to the former, but always LABELLED, never silently.

Every constant below is ordered by evidential strength for that purpose, so
code can compare bases with PREFERENCE_ORDER rather than hard-coding
opinions about which is better.
"""

# Marmon's preferred negotiating position — highest-value basis.
# Derived from a clean initial document diffed against the first redline
# round, so the edits are attributable to one side.
INITIAL_VS_FIRST_REDLINE = "initial_vs_first_redline"

# Same meaning as above, reconstructed from a SINGLE tracked-changes .docx:
# its base rendering (all changes rejected) is what walked into the round,
# its proposed rendering (all changes accepted) is what walked out. Just as
# attributable — the markup carries per-edit authorship — and available even
# when the clean initial document was never uploaded to CobbleStone, which
# is common.
REDLINE_INTERNAL = "redline_internal"

# The negotiated compromise: initial document vs the final/executed version.
# Both sides' edits are blended, so a rule from here is an agreed OUTCOME,
# not a starting position. This is the labelled fallback Jeff described for
# requests whose intermediate documents are missing.
INITIAL_VS_FINAL = "initial_vs_final"

# A clean executed contract with no negotiation history available — evidence
# of an accepted baseline ("this language was signed as-is"), useful as a
# role model but not evidence of any negotiating position.
SINGLE_DOC_BASELINE = "single_doc_baseline"

# Content extracted from a standalone supplementary document (exhibit,
# schedule, attached email) rather than from any diff.
STANDALONE_CONTENT = "standalone_content"

PREFERENCE_ORDER = [
    INITIAL_VS_FIRST_REDLINE,
    REDLINE_INTERNAL,
    INITIAL_VS_FINAL,
    SINGLE_DOC_BASELINE,
    STANDALONE_CONTENT,
]

# Short label for UI chips and the Word document's Basis line.
LABELS = {
    INITIAL_VS_FIRST_REDLINE: "Preferred position",
    REDLINE_INTERNAL: "Preferred position",
    INITIAL_VS_FINAL: "Agreed outcome",
    SINGLE_DOC_BASELINE: "Accepted baseline",
    STANDALONE_CONTENT: "Supplementary",
}

# One-sentence explanation, for the methodology page and tooltips.
DESCRIPTIONS = {
    INITIAL_VS_FIRST_REDLINE:
        "Derived by comparing the initial document against the first redline round — "
        "this is the position Marmon's attorneys asked for before any compromise.",
    REDLINE_INTERNAL:
        "Derived from the tracked changes inside a single redlined Word document "
        "(the document before and after that round's edits) — also a pre-compromise "
        "Marmon position, reconstructed from the markup itself.",
    INITIAL_VS_FINAL:
        "Derived by comparing the initial document against the final executed version — "
        "this reflects the negotiated compromise both parties accepted, which may include "
        "concessions and exceptions proposed by the other side.",
    SINGLE_DOC_BASELINE:
        "Taken from a clean executed contract with no negotiation history available — "
        "evidence that this language was accepted as signed, not evidence of a "
        "negotiating position.",
    STANDALONE_CONTENT:
        "Extracted from a supplementary document (exhibit, schedule, or attached email) "
        "rather than from a comparison between document versions.",
}

# Bases that represent a pre-compromise Marmon position (Jeff's "preferred
# starting position") as opposed to an agreed outcome.
PREFERRED_POSITION_BASES = frozenset({INITIAL_VS_FIRST_REDLINE, REDLINE_INTERNAL})

ALL_BASES = frozenset(PREFERENCE_ORDER)


# ── Position side: WHOSE edits, a separate dimension from the comparison ────
#
# Live finding (2026-08-31) that forced this split: a redline basis alone does
# NOT mean the edits are Marmon's. Across the 100-request US mutual NDA subset,
# 77 first-redlines were confirmed authored by a Marmon attorney, but 23 could
# not be confirmed — and at least one (request 20597, file "...Liberty
# Packaging - LP REDLINE...") is evidently the COUNTERPARTY's redline of our
# draft. Calling that "Marmon's preferred position" would invert its meaning.
#
# So the comparison (which two versions) and the side (whose edits) are tracked
# separately, and the reader-facing label combines them. Jeff's requirement is
# specifically about Marmon's preferred position, so an unconfirmed side must
# read as unconfirmed rather than being quietly counted as ours.
SIDE_MARMON = "marmon"
SIDE_COUNTERPARTY = "counterparty"
SIDE_UNKNOWN = "unknown"

_SIDE_LABELS = {
    (True, SIDE_MARMON): "Marmon preferred position",
    (True, SIDE_COUNTERPARTY): "Counterparty position",
    (True, SIDE_UNKNOWN): "Redline position (side unconfirmed)",
}

_SIDE_DESCRIPTIONS = {
    (True, SIDE_MARMON): (
        "Derived from a redline round whose tracked changes were authored by a Marmon-side "
        "attorney — this is what Marmon asked for before any compromise."),
    (True, SIDE_COUNTERPARTY): (
        "Derived from a redline round authored by the COUNTERPARTY — this is the change the "
        "other side pushed for, not a Marmon position. Useful as intelligence about what "
        "counterparties commonly demand, but do not adopt it as our opening ask."),
    (True, SIDE_UNKNOWN): (
        "Derived from a redline round, but the editing party could not be confirmed from the "
        "document's tracked-change authorship. Treat the position as unattributed: it may be "
        "Marmon's ask or the counterparty's."),
}


def side_label(side: str | None) -> str:
    """Reader-facing name for a side on its own, for summaries that count sides
    across a whole population rather than labelling one rule. Same wording as
    position_label uses, kept in one place so a tally and a rule never disagree
    about what to call the same thing."""
    return _SIDE_LABELS.get((True, side or SIDE_UNKNOWN), _SIDE_LABELS[(True, SIDE_UNKNOWN)])


def position_label(basis: str | None, side: str | None) -> str:
    """Reader-facing label combining the comparison basis with whose edits it
    contains. Falls back to the basis-only label where side is irrelevant
    (an agreed outcome blends both sides by definition; a baseline has no
    edits at all)."""
    if basis in PREFERRED_POSITION_BASES:
        return _SIDE_LABELS.get((True, side or SIDE_UNKNOWN), _SIDE_LABELS[(True, SIDE_UNKNOWN)])
    return label(basis)


def position_describe(basis: str | None, side: str | None) -> str:
    if basis in PREFERRED_POSITION_BASES:
        return _SIDE_DESCRIPTIONS.get((True, side or SIDE_UNKNOWN),
                                       _SIDE_DESCRIPTIONS[(True, SIDE_UNKNOWN)])
    return describe(basis)


def is_marmon_preferred_position(basis: str | None, side: str | None) -> bool:
    """The strict test for Jeff's target: a pre-compromise position that we can
    actually attribute to Marmon. Deliberately excludes unconfirmed sides."""
    return basis in PREFERRED_POSITION_BASES and side == SIDE_MARMON


# Share of ATTRIBUTED edits one side must hold before a rule is labelled that
# side's position. Anything below this reads as unconfirmed.
#
# This used to be pure set membership — a single counterparty edit anywhere in a
# rule's evidence made the whole rule "unconfirmed". That is right when a rule
# rests on ten findings and one of them is theirs: the attribution genuinely is
# a coin flip. It becomes indefensible at population scale, and the 2026-09-01
# full run showed exactly how: MNDA-DEF-01 carried 1,500 Marmon-side edits and
# 12 counterparty edits — 0.8% — and was still labelled unconfirmed, as were 14
# of the 15 rules. The one that escaped had zero counterparty findings by luck,
# not by being better evidenced. A larger, better-evidenced population was
# producing a LESS informative playbook than the 100-contract sample.
#
# 0.9 keeps the original caution where it was earned (2-vs-1 and 5-vs-3 still
# read unconfirmed) while letting overwhelming evidence speak. The raw counts
# travel on every rule as position_side_counts either way, so nothing is hidden
# by the label.
SIDE_DOMINANCE_SHARE = 0.9


def dominant_side(sides) -> str:
    """The side to label a rule with, given its evidence items' sides.

    A rule is called one side's position only when that side holds at least
    SIDE_DOMINANCE_SHARE of the edits that could be attributed at all; a
    genuine mix reads as unconfirmed rather than picking a winner on a narrow
    margin. Unattributed edits ('unknown', None) neither support nor contest a
    side, so they are excluded from the denominator — counting them would let a
    document whose author names Word stripped decide whose position a rule is.
    """
    marmon = sum(1 for s in sides if s == SIDE_MARMON)
    counterparty = sum(1 for s in sides if s == SIDE_COUNTERPARTY)
    attributed = marmon + counterparty
    if not attributed:
        return SIDE_UNKNOWN
    leader, count = ((SIDE_MARMON, marmon) if marmon >= counterparty
                     else (SIDE_COUNTERPARTY, counterparty))
    return leader if count / attributed >= SIDE_DOMINANCE_SHARE else SIDE_UNKNOWN


def is_preferred_position(basis: str) -> bool:
    return basis in PREFERRED_POSITION_BASES


def label(basis: str | None) -> str:
    return LABELS.get(basis, "Unspecified basis")


def describe(basis: str | None) -> str:
    return DESCRIPTIONS.get(basis, "The comparison basis for this rule was not recorded.")


def strongest(bases) -> str | None:
    """The most evidentially valuable basis in a collection — used to label a
    synthesized rule whose evidence spans several requests with different
    bases. Unknown values sort last rather than raising, so a future basis
    added elsewhere can never crash synthesis."""
    known = [b for b in bases if b in ALL_BASES]
    if not known:
        return None
    return min(known, key=PREFERENCE_ORDER.index)


def rollup(bases) -> dict:
    """Deterministic provenance summary for a synthesized rule's evidence set.

    Returns {"dominant", "counts", "preferred_position_count", "total",
    "summary"} where `summary` is the human-readable string that goes on the
    rule's Basis line, e.g. "Preferred position — 14 of 18 evidence items".
    Counting is plain arithmetic, deliberately not an LLM judgement, so the
    number an attorney reads is reproducible."""
    counts: dict[str, int] = {}
    for b in bases:
        counts[b] = counts.get(b, 0) + 1
    total = sum(counts.values())
    dominant = strongest(counts)
    pref = sum(n for b, n in counts.items() if b in PREFERRED_POSITION_BASES)
    if not total:
        summary = "No comparison basis recorded"
    elif pref == total:
        summary = f"Preferred position — all {total} evidence item{'s' if total != 1 else ''}"
    elif pref:
        summary = f"Mixed — {pref} of {total} evidence items are a pre-compromise Marmon position"
    else:
        summary = f"{label(dominant)} — {total} evidence item{'s' if total != 1 else ''}"
    return {
        "dominant": dominant,
        "counts": counts,
        "preferred_position_count": pref,
        "total": total,
        "summary": summary,
    }
